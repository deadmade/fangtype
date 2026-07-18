"""AST utilities for creating/manipulating AST nodes from Jedi inference results."""

import ast
from typing import Protocol


class JediNameLike(Protocol):
    """Minimal protocol for Jedi name-like objects."""

    name: str
    type: str
    line: int | None
    column: int | None


def create_ast_node(name: JediNameLike) -> ast.AST:
    """Create a ClassDef/FunctionDef AST node with line/col info from a Jedi name."""
    line = name.line if name.line is not None else 1
    col = name.column if name.column is not None else 0

    node: ast.ClassDef | ast.FunctionDef
    if name.type == "class":
        node = ast.ClassDef(
            name=name.name,
            bases=[],
            keywords=[],
            body=[ast.Pass()],
            decorator_list=[],
            type_params=[],
        )
    else:
        node = ast.FunctionDef(
            name=name.name,
            args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]),
            body=[ast.Pass()],
            decorator_list=[],
            type_params=[],
        )

    node.lineno = line
    node.col_offset = col
    node.end_lineno = line
    node.end_col_offset = col + len(name.name)

    ast.fix_missing_locations(node)

    return node
