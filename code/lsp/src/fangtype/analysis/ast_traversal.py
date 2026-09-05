"""Shared AST traversal helpers used across inference and insertion logic."""

from __future__ import annotations

import ast

# The implicit first parameter of a method, under both its conventional names.
SELF_LIKE_NAMES = ("self", "cls")


def is_implicit_receiver(func_node: ast.AST, param_name: str, *, in_class: bool) -> bool:
    """True when ``param_name`` is the receiver a method gets for free.

    A checker already knows what the receiver refers to, so annotating it adds nothing a
    reader or a checker can use. The test is positional rather than by name alone, so a
    parameter merely called ``self`` in a plain function or a staticmethod is left alone.
    """
    if not in_class or param_name not in SELF_LIKE_NAMES:
        return False
    if not isinstance(func_node, ast.FunctionDef | ast.AsyncFunctionDef):
        return False
    if any(isinstance(d, ast.Name) and d.id == "staticmethod" for d in func_node.decorator_list):
        return False
    positional = [*func_node.args.posonlyargs, *func_node.args.args]
    return bool(positional) and positional[0].arg == param_name


def set_parent_refs(node: ast.AST, parent: ast.AST | None = None) -> None:
    """Set ``parent`` references on a full AST subtree."""
    node.parent = parent  # type: ignore[attr-defined]
    for child in ast.iter_child_nodes(node):
        set_parent_refs(child, node)


def extract_loop_variables(node: ast.AST) -> list[str]:
    """Extract variable names from a loop target (including unpacking)."""
    variables: list[str] = []
    if isinstance(node, ast.Name):
        variables.append(node.id)
    elif isinstance(node, ast.Starred):
        variables.extend(extract_loop_variables(node.value))
    elif isinstance(node, ast.Tuple | ast.List):
        for element in node.elts:
            variables.extend(extract_loop_variables(element))
    return variables


def _dotted_target_name(node: ast.expr) -> str | None:
    """Render an annotation target as its source spelling, or None if it is not a plain chain."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_target_name(node.value)
        return f"{base}.{node.attr}" if base is not None else None
    return None


def annotated_targets_by_line(node: ast.AST) -> dict[int, set[str]]:
    """Map a 0-based line to the names carrying a PEP 526 annotation on it.

    A bare target is recorded as ``x`` and an attribute target as its dotted source
    spelling, as in ``self.width`` or ``point.x``, because that is how callers name them.
    A subscript target such as ``d["k"]: int`` binds nothing and is skipped.

    Unlike a scope-keyed annotation set, this may use ``ast.walk`` freely. Entries are
    keyed by line, and a nested def's annotations sit on their own lines, so descending
    into one cannot leak an annotation into the enclosing scope.
    """
    annotated: dict[int, set[str]] = {}
    for child in ast.walk(node):
        if not isinstance(child, ast.AnnAssign):
            continue
        name = _dotted_target_name(child.target)
        if name is not None:
            annotated.setdefault(child.target.lineno - 1, set()).add(name)
    return annotated


def _block_bodies(statement: ast.stmt) -> list[list[ast.stmt]]:
    """Statement lists a compound statement can nest defs in (if/for/while/with/try/match)."""
    if isinstance(statement, (ast.If, ast.For, ast.AsyncFor, ast.While)):
        return [statement.body, statement.orelse]
    if isinstance(statement, (ast.With, ast.AsyncWith)):
        return [statement.body]
    if isinstance(statement, (ast.Try, ast.TryStar)):
        return [
            statement.body,
            statement.orelse,
            statement.finalbody,
            *(handler.body for handler in statement.handlers),
        ]
    if isinstance(statement, ast.Match):
        return [case.body for case in statement.cases]
    return []


def iter_qualified_function_nodes(
    body: list[ast.stmt], prefix: str = ""
) -> list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """Enumerate function nodes with qualified names."""
    items: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]] = []
    for statement in body:
        if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef):
            qualified_name = f"{prefix}.{statement.name}" if prefix else statement.name
            items.append((qualified_name, statement))
            items.extend(iter_qualified_function_nodes(statement.body, qualified_name))
        elif isinstance(statement, ast.ClassDef):
            class_prefix = f"{prefix}.{statement.name}" if prefix else statement.name
            items.extend(iter_qualified_function_nodes(statement.body, class_prefix))
        else:
            # Functions nested under if/for/while/with/try keep the enclosing prefix.
            for child_body in _block_bodies(statement):
                items.extend(iter_qualified_function_nodes(child_body, prefix))
    return items
