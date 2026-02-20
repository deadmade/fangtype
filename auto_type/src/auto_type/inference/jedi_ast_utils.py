"""AST utilities for Jedi inference.

This module provides helper functions for creating and manipulating AST nodes
when working with Jedi inference results.
"""

import ast
from typing import Protocol


class JediNameLike(Protocol):
    """Minimal protocol for Jedi name-like objects."""

    name: str
    type: str
    line: int | None
    column: int | None


def create_ast_node(name: JediNameLike) -> ast.AST:
    """Create an AST node for a Jedi name when real AST node is not available.

    Args:
        name: Jedi Name object containing type and location information

    Returns:
        AST node (ClassDef or FunctionDef) with proper line/column info
    """
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

    return node
