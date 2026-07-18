"""Tests for fangtype.inference.jedi.scope_builder._infer_return_type_from_ast_node.

This helper is the AST fallback that fires only after ``recover_return_union_from_node``
(type_recovery.py) has already deferred -- i.e. when at least one return branch is not an
all-literal value. It must mirror that sibling's "any unrecognized branch -> defer" discipline
instead of silently narrowing to whichever container literal it does recognize.
"""

import ast
import textwrap


def _func_node(source: str, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for node in ast.walk(ast.parse(textwrap.dedent(source).strip())):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"function {name!r} not found")


def test_defers_when_container_return_mixed_with_unclassified_branch() -> None:
    """A container return alongside a branch this can't classify -- defer, don't narrow."""
    from fangtype.inference.jedi.scope_builder import _infer_return_type_from_ast_node

    source = """
        def f(flag):
            if flag:
                return undefined_symbol
            return []
    """
    assert _infer_return_type_from_ast_node(_func_node(source, "f")) is None


def test_single_recognized_container_return_still_narrows() -> None:
    """A function with only one, recognized container return still yields that type."""
    from fangtype.inference.jedi.scope_builder import _infer_return_type_from_ast_node

    source = """
        def f():
            return []
    """
    assert _infer_return_type_from_ast_node(_func_node(source, "f")) == "list"


def test_defers_for_bare_none_return_alongside_container() -> None:
    """A container return alongside a bare ``return None`` is partial knowledge -- defer."""
    from fangtype.inference.jedi.scope_builder import _infer_return_type_from_ast_node

    source = """
        def f(flag):
            if flag:
                return []
            return None
    """
    assert _infer_return_type_from_ast_node(_func_node(source, "f")) is None


def test_nested_unclassified_return_does_not_force_outer_to_defer() -> None:
    """An unclassified return inside a nested function must not leak into the outer scope."""
    from fangtype.inference.jedi.scope_builder import _infer_return_type_from_ast_node

    source = """
        def outer():
            def helper():
                return compute()
            return []
    """
    assert _infer_return_type_from_ast_node(_func_node(source, "outer")) == "list"


def test_nested_different_container_return_does_not_leak_into_outer() -> None:
    """A nested function's own container return must not merge into the outer's return set."""
    from fangtype.inference.jedi.scope_builder import _infer_return_type_from_ast_node

    source = """
        def outer():
            def helper():
                return {}
            return []
    """
    assert _infer_return_type_from_ast_node(_func_node(source, "outer")) == "list"
