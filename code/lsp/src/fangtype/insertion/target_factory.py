"""Shared helpers for building insertion targets."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from fangtype.analysis.ast_traversal import extract_loop_variables, iter_qualified_function_nodes
from fangtype.insertion.types import CodeLocation, InsertionTarget, TargetType

if TYPE_CHECKING:
    from fangtype.analysis.types import ImportHint


@dataclass(frozen=True)
class AssignmentTarget:
    """Resolved assignment location and target type for a variable."""

    line_1_based: int
    target_type: TargetType
    # Line of the innermost enclosing def/class, 0 for module scope. Candidates are indexed by
    # bare name across the whole file, so this is what keeps "prefer an earlier binding" from
    # reaching into another function that reuses the name.
    scope_key: int = 0


@dataclass(frozen=True)
class SourceIndex:
    """Parsed source index for efficient assignment and function lookups."""

    tree: ast.Module
    assignment_candidates_by_name: dict[str, list[AssignmentTarget]]
    function_lines_by_qualified: dict[str, int]
    function_lines_by_simple: dict[str, int]


def find_variable_line(source: str, variable_name: str) -> int:
    """Find a variable's assignment line via AST index; text-scan fallback if unparseable."""
    index = build_source_index(source)
    if index is not None:
        candidates = index.assignment_candidates_by_name.get(variable_name)
        if candidates:
            return min(candidate.line_1_based for candidate in candidates)
        return 1

    assign_pattern = re.compile(rf"\b{re.escape(variable_name)}\s*=(?!=)")
    for line_number, line in enumerate(source.splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        if assign_pattern.search(line):
            return line_number
    return 1


def _get_attribute_name(node: ast.Attribute) -> str:
    """Build full attribute name from an Attribute node (e.g., 'self.value')."""
    parts: list[str] = []
    current: ast.AST = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


def _target_contains_name(target: ast.AST, var_name: str) -> bool:
    """Check whether assignment target contains var_name."""
    if isinstance(target, ast.Name):
        return target.id == var_name
    if isinstance(target, ast.Attribute):
        return _get_attribute_name(target) == var_name
    if isinstance(target, ast.Tuple | ast.List):
        return any(
            isinstance(element, ast.AST) and _target_contains_name(element, var_name)
            for element in target.elts
        )
    if isinstance(target, ast.Starred):
        return _target_contains_name(target.value, var_name)
    return False


def _target_identifiers(target: ast.AST) -> list[str]:
    """Extract all concrete identifiers represented by a target node."""
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Attribute):
        return [_get_attribute_name(target)]
    if isinstance(target, ast.Tuple | ast.List):
        names: list[str] = []
        for element in target.elts:
            names.extend(_target_identifiers(element))
        return names
    if isinstance(target, ast.Starred):
        return _target_identifiers(target.value)
    return []


def _candidate_type_for_target(target: ast.AST, value: ast.AST, var_name: str) -> TargetType | None:
    """Infer target type for a concrete assignment target node."""
    if isinstance(target, ast.Tuple | ast.List) and _target_contains_name(target, var_name):
        return TargetType.VARIABLE_COMPLEX

    if isinstance(target, ast.Attribute) and _target_contains_name(target, var_name):
        return TargetType.ATTRIBUTE_ACCESS

    if isinstance(target, ast.Name) and target.id == var_name:
        if isinstance(value, ast.Subscript):
            return TargetType.SUBSCRIPT_ACCESS
        if isinstance(value, ast.Attribute):
            return TargetType.ATTRIBUTE_ACCESS
        return TargetType.VARIABLE_SIMPLE

    if isinstance(target, ast.Starred):
        return _candidate_type_for_target(target.value, value, var_name)

    return None


def _augassign_candidate_type_for_target(target: ast.AST, var_name: str) -> TargetType | None:
    """Infer target type for augmented assignments (x += 1)."""
    if isinstance(target, ast.Attribute) and _target_contains_name(target, var_name):
        # Attribute AugAssign can't be rewritten in place; prefer the latest plain assignment.
        return None
    if isinstance(target, ast.Name) and target.id == var_name:
        # Augmented assignments cannot be converted in-place; use declaration fallback.
        return TargetType.VARIABLE_COMPLEX
    if isinstance(target, ast.Subscript) and _target_contains_name(target, var_name):
        return TargetType.VARIABLE_COMPLEX
    return None


def _build_scope_spans(tree: ast.Module) -> list[tuple[int, int, int]]:
    """(start, end, key) line spans for every def/class in the module, key being the start line.

    Module scope is the absence of a containing span rather than an entry, so it needs no key
    of its own beyond the 0 that ``_scope_key_for_line`` falls back to.
    """
    spans: list[tuple[int, int, int]] = []
    for node in ast.walk(tree):
        # Tuple form, not `A | B | C`: the three-way UnionType expression leaks Any under
        # disallow_any_expr, while the two-way one used elsewhere in the codebase does not.
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            end = node.end_lineno if node.end_lineno is not None else node.lineno
            spans.append((node.lineno, end, node.lineno))
    return spans


def _scope_key_for_line(spans: list[tuple[int, int, int]], line_1_based: int) -> int:
    """Key of the innermost span containing the line, 0 when the line is at module scope.

    Innermost is the latest-starting containing span, since a nested def always opens after
    the one enclosing it.
    """
    key = 0
    best_start = 0
    for start, end, span_key in spans:
        if start <= line_1_based <= end and start >= best_start:
            best_start = start
            key = span_key
    return key


def build_source_index(source: str) -> SourceIndex | None:
    """Build a reusable source index for assignment and function lookups."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    scope_spans = _build_scope_spans(tree)

    assignment_candidates_by_name: dict[str, list[AssignmentTarget]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            # Chained assigns → bare-Name promoted to VARIABLE_COMPLEX to avoid dropping targets.
            is_chained = len(node.targets) > 1
            for target in node.targets:
                for identifier in _target_identifiers(target):
                    target_type = _candidate_type_for_target(target, node.value, identifier)
                    if target_type is None:
                        continue
                    if is_chained and target_type == TargetType.VARIABLE_SIMPLE:
                        target_type = TargetType.VARIABLE_COMPLEX
                    assignment_candidates_by_name.setdefault(identifier, []).append(
                        AssignmentTarget(
                            line_1_based=node.lineno,
                            target_type=target_type,
                            scope_key=_scope_key_for_line(scope_spans, node.lineno),
                        )
                    )
        elif isinstance(node, ast.AugAssign):
            for identifier in _target_identifiers(node.target):
                target_type = _augassign_candidate_type_for_target(node.target, identifier)
                if target_type is None:
                    continue
                assignment_candidates_by_name.setdefault(identifier, []).append(
                    AssignmentTarget(
                        line_1_based=node.lineno,
                        target_type=target_type,
                        scope_key=_scope_key_for_line(scope_spans, node.lineno),
                    )
                )
        elif isinstance(node, ast.NamedExpr):
            for identifier in _target_identifiers(node.target):
                assignment_candidates_by_name.setdefault(identifier, []).append(
                    AssignmentTarget(
                        line_1_based=node.lineno,
                        # Walrus targets need pre-declaration; no in-place rewrite available.
                        target_type=TargetType.VARIABLE_COMPLEX,
                        scope_key=_scope_key_for_line(scope_spans, node.lineno),
                    )
                )
        elif isinstance(node, ast.For | ast.AsyncFor):
            for var_name in extract_loop_variables(node.target):
                assignment_candidates_by_name.setdefault(var_name, []).append(
                    AssignmentTarget(
                        line_1_based=node.lineno,
                        target_type=TargetType.ITERATION_VARIABLE,
                        scope_key=_scope_key_for_line(scope_spans, node.lineno),
                    )
                )
        # Comprehension/genexp loop targets are deliberately not registered (never annotatable).

    function_lines_by_qualified: dict[str, int] = {}
    function_lines_by_simple: dict[str, int] = {}
    for qualified_name, function_node in iter_qualified_function_nodes(tree.body):
        function_lines_by_qualified[qualified_name] = function_node.lineno
        function_lines_by_simple.setdefault(function_node.name, function_node.lineno)

    return SourceIndex(
        tree=tree,
        assignment_candidates_by_name=assignment_candidates_by_name,
        function_lines_by_qualified=function_lines_by_qualified,
        function_lines_by_simple=function_lines_by_simple,
    )


# Target types with no in-place rewrite: PEP 526 cannot annotate the binding itself, so the
# engine writes a standalone `x: T` declaration above the statement instead.
_DECLARATION_FORCING = frozenset({TargetType.VARIABLE_COMPLEX, TargetType.ITERATION_VARIABLE})

# Target types the engine can annotate where the binding already stands.
_INPLACE_ANNOTATABLE = frozenset(
    {TargetType.VARIABLE_SIMPLE, TargetType.SUBSCRIPT_ACCESS, TargetType.ATTRIBUTE_ACCESS}
)


def _candidate_line(candidate: AssignmentTarget) -> int:
    return candidate.line_1_based


def _prefer_earlier_binding(
    candidates: list[AssignmentTarget], selected: AssignmentTarget
) -> AssignmentTarget:
    """Redirect a declaration away from the newest binding of a name to an earlier one.

    A declaration written above the newest binding lands after every earlier binding of the
    same name, which mypy reports as `no-redef` — the accumulator idiom `total = 0` followed by
    `total += n` puts the declaration inside the loop. Annotating the earliest in-place binding
    instead both avoids the redefinition and states the type where the value first arrives.

    Restricted to the selected binding's own scope, because candidates are indexed by bare name
    across the whole file and an earlier `total` may belong to a different function.
    """
    if selected.target_type not in _DECLARATION_FORCING:
        return selected

    in_scope = [
        candidate
        for candidate in candidates
        if candidate.scope_key == selected.scope_key
        and candidate.line_1_based <= selected.line_1_based
    ]
    inplace = [c for c in in_scope if c.target_type in _INPLACE_ANNOTATABLE]
    if inplace:
        return min(inplace, key=_candidate_line)

    # No binding this can be written onto, so the declaration stands — but above the first
    # binding in the scope, which no earlier one then precedes.
    return min(in_scope, key=_candidate_line) if in_scope else selected


def _select_assignment_target(
    candidates: list[AssignmentTarget], line_hint_0: int | None
) -> AssignmentTarget:
    """Select the best assignment candidate for an optional hint line."""
    if line_hint_0 is None:
        return _prefer_earlier_binding(candidates, candidates[0])

    hint_1 = line_hint_0 + 1

    def distance_to_hint(candidate: AssignmentTarget) -> int:
        return abs(candidate.line_1_based - hint_1)

    at_or_before = [candidate for candidate in candidates if candidate.line_1_based <= hint_1]
    if at_or_before:
        return _prefer_earlier_binding(candidates, max(at_or_before, key=_candidate_line))

    return _prefer_earlier_binding(candidates, min(candidates, key=distance_to_hint))


def find_assignment_target_indexed(
    index: SourceIndex, var_name: str, line_hint_0: int | None = None
) -> AssignmentTarget | None:
    """Resolve the best assignment line and target type for a variable from an index."""
    candidates = index.assignment_candidates_by_name.get(var_name, [])
    if not candidates:
        return None
    return _select_assignment_target(candidates, line_hint_0)


def detect_assignment_pattern_indexed(index: SourceIndex, var_name: str, line_0: int) -> TargetType:
    """Detect assignment pattern type for a variable at a specific 0-based line."""
    resolved = find_assignment_target_indexed(index, var_name, line_0)
    if resolved is None or resolved.line_1_based != line_0 + 1:
        return TargetType.VARIABLE_SIMPLE
    return resolved.target_type


def detect_assignment_pattern(source: str, var_name: str, line_0: int) -> TargetType:
    """Detect assignment pattern type for a variable at a specific 0-based line."""
    index = build_source_index(source)
    if index is None:
        return TargetType.VARIABLE_SIMPLE
    return detect_assignment_pattern_indexed(index, var_name, line_0)


def find_assignment_target(
    source: str, var_name: str, line_hint_0: int | None = None
) -> AssignmentTarget | None:
    """Resolve the best assignment line and target type for a variable, or None if not found."""
    index = build_source_index(source)
    if index is None:
        return None
    return find_assignment_target_indexed(index, var_name, line_hint_0)


def find_function_line_indexed(index: SourceIndex, function_name: str) -> int:
    """Find function definition line for simple or qualified names from an index."""
    qualified_line = index.function_lines_by_qualified.get(function_name)
    if qualified_line is not None:
        return qualified_line

    simple_name = function_name.split(".")[-1]
    fallback_line = index.function_lines_by_simple.get(simple_name)
    return fallback_line if fallback_line is not None else 1


def find_function_line(source: str, function_name: str) -> int:
    """Find function definition line for simple or qualified function names."""
    index = build_source_index(source)
    if index is not None:
        return find_function_line_indexed(index, function_name)

    simple_name = function_name.split(".")[-1]
    for line_number, line in enumerate(source.splitlines(), 1):
        if f"def {simple_name}(" in line or f"async def {simple_name}(" in line:
            return line_number
    return 1


def create_variable_target(
    name: str,
    type_annotation: str,
    line: int,
    target_type: TargetType = TargetType.VARIABLE_SIMPLE,
    import_hint: ImportHint | None = None,
) -> InsertionTarget:
    """Create an insertion target for a variable annotation."""
    return InsertionTarget(
        target_type=target_type,
        location=CodeLocation(line=line, column=0),
        type_annotation=type_annotation,
        name=name,
        import_hint=import_hint,
    )
