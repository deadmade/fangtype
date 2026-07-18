"""Shared AST traversal helpers used across inference and insertion logic."""

from __future__ import annotations

import ast


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
