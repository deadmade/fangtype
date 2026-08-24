"""Tests for shared AST traversal helpers."""

import ast

from fangtype.analysis.ast_traversal import (
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


def test_extract_loop_variables_captures_starred_target() -> None:
    """`for a, *rest in seq` must keep the starred `rest` name (L7)."""
    tree = ast.parse("for a, *rest in seq: pass")
    loop = tree.body[0]
    assert isinstance(loop, ast.For)

    assert extract_loop_variables(loop.target) == ["a", "rest"]


def test_iter_qualified_function_nodes_finds_functions_in_compound_statements() -> None:
    """Functions defined under if/try/with/for are enumerated, keeping the enclosing prefix (L8)."""
    source = """
if True:
    def guarded():
        pass

class User:
    if COND:
        def conditional_method(self):
            pass

try:
    def in_try():
        pass
except Exception:
    def in_handler():
        pass
"""
    tree = ast.parse(source)
    names = [name for name, _ in iter_qualified_function_nodes(tree.body)]

    assert "guarded" in names
    assert "User.conditional_method" in names
    assert "in_try" in names
    assert "in_handler" in names


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
