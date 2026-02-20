"""Tests for shared AST traversal helpers."""

import ast

from auto_type.analysis.ast_traversal import (
    extract_loop_variables,
    iter_qualified_function_nodes,
    set_parent_refs,
)


def test_extract_loop_variables_nested_targets() -> None:
    """Should extract nested loop variables from tuple/list targets."""
    tree = ast.parse("for a, (b, [c, d]) in seq: pass")
    loop = tree.body[0]
    assert isinstance(loop, ast.For)

    assert extract_loop_variables(loop.target) == ["a", "b", "c", "d"]


def test_iter_qualified_function_nodes_includes_nested_and_methods() -> None:
    """Should emit qualified names for nested functions and class methods."""
    source = """
def top():
    def inner():
        pass

class User:
    def method(self):
        pass
"""
    tree = ast.parse(source)
    items = iter_qualified_function_nodes(tree.body)
    names = [name for name, _ in items]

    assert names == ["top", "top.inner", "User.method"]


def test_set_parent_refs_assigns_parent_links() -> None:
    """Should set parent references for traversable AST nodes."""
    tree = ast.parse("x = 1\n")
    set_parent_refs(tree)

    assign = tree.body[0]
    assert isinstance(assign, ast.Assign)
    assert getattr(assign, "parent", None) is tree

    target = assign.targets[0]
    assert isinstance(target, ast.Name)
    assert getattr(target, "parent", None) is assign
