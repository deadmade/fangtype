"""Forward-reference detection for annotations the tool is about to write.

Up to CPython 3.13 the annotations on a ``def`` are evaluated the moment the ``def``
statement executes, and annotations at module or class level are evaluated where they
stand. Writing a name that is not bound yet at that point turns a working module into one
that raises ``NameError`` on import. PEP 649 made annotations lazy from 3.14, but
``requires-python`` is ``>=3.12``, so the tool cannot rely on that.

mypy accepts the broken form, so the validation stage cannot catch this. The repair is the
PEP 484 string form, ``x: "Node"``, which is legal on every version and which mypy resolves
identically.

Two situations produce an unbound name.

* A method annotated with its own class. The class name binds only after the class body
  finishes, so it is unavailable to every ``def`` inside that body. This holds at any
  nesting depth, including a class defined inside a function.
* A name bound later in the module than the statement referring to it, which reaches
  module-level and class-level statements only. Inside a function body the module has
  finished executing by the time the statement runs.
* A name that only ever binds inside a function body, which inference can still reach and
  name. It is invisible from module level whatever the order, so a signature out there can
  never evaluate it.

Annotations inside a function body are never evaluated at runtime, so they need no repair.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field


def _referenced_names(type_str: str) -> set[str]:
    """Bare names an annotation expression evaluates, ignoring any already-quoted part."""
    try:
        expr = ast.parse(type_str.strip(), mode="eval")
    except SyntaxError:
        # Not parseable as an expression. sanitize_type_annotation rejects it downstream.
        return set()
    # ast.Attribute walks down to its root ast.Name, so ``a.b.C`` yields ``a`` and nothing
    # else — which is the only name the expression actually looks up.
    return {node.id for node in ast.walk(expr) if isinstance(node, ast.Name)}


def is_quoted(type_str: str) -> bool:
    """True when the whole annotation is already a single string literal."""
    try:
        expr = ast.parse(type_str.strip(), mode="eval")
    except SyntaxError:
        return False
    return isinstance(expr.body, ast.Constant) and isinstance(expr.body.value, str)


def quote_annotation(type_str: str) -> str:
    """Wrap a whole annotation as a PEP 484 forward reference.

    The whole expression is wrapped rather than the offending name inside it, so
    ``dict[str, Node]`` becomes ``"dict[str, Node]"``. Both are legal and equivalent to a
    checker, and wrapping avoids rebuilding subscript interiors.
    """
    stripped = type_str.strip()
    if '"' not in stripped:
        return f'"{stripped}"'
    if "'" not in stripped:
        return f"'{stripped}'"
    # Both quote styles already occur inside. Nesting a third would not parse, and this
    # cannot arise from an inferred type today, so leave it and let the caller write it raw.
    return stripped


@dataclass(frozen=True)
class ForwardRefContext:
    """Answers whether an annotation written at a given line would fail to evaluate."""

    # Statement line (1-based) -> names of the classes whose body lexically contains it.
    enclosing_classes: dict[int, frozenset[str]] = field(default_factory=dict)
    # Module-visible name -> the line at which it finishes binding.
    binding_lines: dict[str, int] = field(default_factory=dict)
    # Statement lines (1-based) that execute outside any function body.
    eager_lines: frozenset[int] = frozenset()
    # Classes and functions defined inside a function body, so never visible from module level.
    function_local_names: frozenset[str] = frozenset()

    def needs_quoting(self, type_str: str, line: int) -> bool:
        """True when writing ``type_str`` at 1-based ``line`` would raise NameError."""
        if is_quoted(type_str):
            return False

        names = _referenced_names(type_str)
        if not names:
            return False

        if names & self.enclosing_classes.get(line, frozenset()):
            return True

        if line not in self.eager_lines:
            # Inside a function body: never evaluated, or evaluated once the module is done.
            return False

        if names & self.function_local_names:
            return True

        return any(
            (bound := self.binding_lines.get(name)) is not None and bound >= line for name in names
        )

    def quote_if_needed(self, type_str: str, line: int) -> str:
        """Return ``type_str`` as-is, or as a forward reference when it would not evaluate."""
        if not self.needs_quoting(type_str, line):
            return type_str
        return quote_annotation(type_str)


class _ScopeWalker(ast.NodeVisitor):
    """Collects binding order and class nesting in one pass."""

    def __init__(self) -> None:
        self.enclosing_classes: dict[int, frozenset[str]] = {}
        self.binding_lines: dict[str, int] = {}
        self.eager_lines: set[int] = set()
        self.function_local_names: set[str] = set()
        self._class_stack: list[str] = []
        self._function_depth = 0

    def _bind_definition(self, name: str, end_line: int) -> None:
        """Record a class or function, as module-visible or as reachable only from inside one."""
        if self._function_depth == 0:
            self._bind(name, end_line)
        else:
            self.function_local_names.add(name)

    def _bind(self, name: str, end_line: int) -> None:
        """Record where a module-visible name finishes binding, keeping the latest."""
        previous = self.binding_lines.get(name)
        if previous is None or end_line > previous:
            self.binding_lines[name] = end_line

    def _mark(self, node: ast.stmt) -> None:
        """Record the class nesting, and the eagerness, of a statement carrying annotations."""
        if self._class_stack:
            self.enclosing_classes[node.lineno] = frozenset(self._class_stack)
        if self._function_depth == 0:
            self.eager_lines.add(node.lineno)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        # The signature is evaluated where the def stands, so it is marked at the outer depth.
        self._mark(node)
        self._bind_definition(node.name, node.end_lineno or node.lineno)
        self._function_depth += 1
        self.generic_visit(node)
        self._function_depth -= 1

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Walk a class body, which executes eagerly and does not introduce a function scope."""
        # The name binds only once the body is complete, which is what makes a method's
        # annotation of its own class fail.
        self._bind_definition(node.name, node.end_lineno or node.lineno)
        self._class_stack.append(node.name)
        self.generic_visit(node)
        self._class_stack.pop()

    def visit_Lambda(self, node: ast.Lambda) -> None:
        """Treat a lambda body as a function scope; it carries no annotations of its own."""
        self._function_depth += 1
        self.generic_visit(node)
        self._function_depth -= 1

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """Record an annotated binding, whose annotation is evaluated outside a function."""
        self._mark(node)
        if self._function_depth == 0 and isinstance(node.target, ast.Name):
            self._bind(node.target.id, node.lineno)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        """Record a plain binding, which is where the tool would add an annotation."""
        self._mark(node)
        if self._function_depth == 0:
            for target in node.targets:
                for name in ast.walk(target):
                    if isinstance(name, ast.Name):
                        self._bind(name.id, node.lineno)
        self.generic_visit(node)

    def _visit_import(self, node: ast.Import | ast.ImportFrom) -> None:
        if self._function_depth == 0:
            for alias in node.names:
                self._bind(alias.asname or alias.name.split(".", 1)[0], node.lineno)
        self.generic_visit(node)

    visit_Import = _visit_import
    visit_ImportFrom = _visit_import


def build_forward_ref_context(source: str) -> ForwardRefContext:
    """Build the context for ``source``; an unparseable module yields an empty context."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ForwardRefContext()

    walker = _ScopeWalker()
    walker.visit(tree)
    return ForwardRefContext(
        enclosing_classes=walker.enclosing_classes,
        binding_lines=walker.binding_lines,
        eager_lines=frozenset(walker.eager_lines),
        function_local_names=frozenset(walker.function_local_names),
    )
