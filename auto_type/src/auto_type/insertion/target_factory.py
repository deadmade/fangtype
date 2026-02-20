"""Shared helpers for building insertion targets."""

from __future__ import annotations

import ast
from dataclasses import dataclass

from auto_type.analysis.ast_traversal import extract_loop_variables, iter_qualified_function_nodes
from auto_type.insertion.types import CodeLocation, InsertionTarget, TargetType


@dataclass(frozen=True)
class AssignmentTarget:
    """Resolved assignment location and target type for a variable."""

    line_1_based: int
    target_type: TargetType


@dataclass(frozen=True)
class SourceIndex:
    """Parsed source index for efficient assignment and function lookups."""

    tree: ast.Module
    assignment_candidates_by_name: dict[str, list[AssignmentTarget]]
    function_lines_by_qualified: dict[str, int]
    function_lines_by_simple: dict[str, int]


def find_variable_line(source: str, variable_name: str) -> int:
    """Find the line number where a variable is assigned.

    Args:
        source: Python source code
        variable_name: Variable name to search for

    Returns:
        1-based line number for the assignment, or 1 as fallback
    """
    for line_number, line in enumerate(source.splitlines(), 1):
        if f"{variable_name} =" in line and not line.strip().startswith("#"):
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
        # Prefer the latest plain assignment for attribute targets (e.g. self.n = 0)
        # because attribute AugAssign cannot be converted in-place by the transformer.
        return None
    if isinstance(target, ast.Name) and target.id == var_name:
        # Augmented assignments cannot be converted in-place; use declaration fallback.
        return TargetType.VARIABLE_COMPLEX
    if isinstance(target, ast.Subscript) and _target_contains_name(target, var_name):
        return TargetType.VARIABLE_COMPLEX
    return None


def build_source_index(source: str) -> SourceIndex | None:
    """Build a reusable source index for assignment and function lookups."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    assignment_candidates_by_name: dict[str, list[AssignmentTarget]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                for identifier in _target_identifiers(target):
                    target_type = _candidate_type_for_target(target, node.value, identifier)
                    if target_type is None:
                        continue
                    assignment_candidates_by_name.setdefault(identifier, []).append(
                        AssignmentTarget(line_1_based=node.lineno, target_type=target_type)
                    )
        elif isinstance(node, ast.AugAssign):
            for identifier in _target_identifiers(node.target):
                target_type = _augassign_candidate_type_for_target(node.target, identifier)
                if target_type is None:
                    continue
                assignment_candidates_by_name.setdefault(identifier, []).append(
                    AssignmentTarget(line_1_based=node.lineno, target_type=target_type)
                )
        elif isinstance(node, ast.NamedExpr):
            for identifier in _target_identifiers(node.target):
                assignment_candidates_by_name.setdefault(identifier, []).append(
                    AssignmentTarget(
                        line_1_based=node.lineno,
                        # Walrus targets need pre-declaration; no in-place rewrite available.
                        target_type=TargetType.VARIABLE_COMPLEX,
                    )
                )
        elif isinstance(node, ast.For | ast.AsyncFor):
            for var_name in extract_loop_variables(node.target):
                assignment_candidates_by_name.setdefault(var_name, []).append(
                    AssignmentTarget(
                        line_1_based=node.lineno,
                        target_type=TargetType.ITERATION_VARIABLE,
                    )
                )
        elif isinstance(node, ast.GeneratorExp | ast.ListComp | ast.SetComp | ast.DictComp):
            generators = node.generators if hasattr(node, "generators") else []
            for generator in generators:
                for var_name in extract_loop_variables(generator.target):
                    assignment_candidates_by_name.setdefault(var_name, []).append(
                        AssignmentTarget(
                            line_1_based=node.lineno,
                            target_type=TargetType.ITERATION_VARIABLE,
                        )
                    )

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


def _select_assignment_target(
    candidates: list[AssignmentTarget], line_hint_0: int | None
) -> AssignmentTarget:
    """Select the best assignment candidate for an optional hint line."""
    if line_hint_0 is None:
        return candidates[0]

    hint_1 = line_hint_0 + 1

    at_or_before = [candidate for candidate in candidates if candidate.line_1_based <= hint_1]
    if at_or_before:
        return max(at_or_before, key=lambda candidate: candidate.line_1_based)

    return min(candidates, key=lambda candidate: abs(candidate.line_1_based - hint_1))


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
    """Resolve the best assignment line and target type for a variable.

    Args:
        source: Python source code
        var_name: Variable name to resolve
        line_hint_0: Optional 0-based hint line from inference context

    Returns:
        AssignmentTarget if a matching assignment is found, None otherwise
    """
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
) -> InsertionTarget:
    """Create an insertion target for a variable annotation.

    Args:
        name: Variable name
        type_annotation: Type annotation string
        line: 1-based line number for insertion
        target_type: Target insertion strategy type

    Returns:
        Configured insertion target
    """
    return InsertionTarget(
        target_type=target_type,
        location=CodeLocation(line=line, column=0),
        type_annotation=type_annotation,
        name=name,
    )
