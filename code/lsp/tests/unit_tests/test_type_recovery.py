"""Tests for fangtype.inference.type_recovery helpers."""

import ast
import textwrap


def _func_node(source: str, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for node in ast.walk(ast.parse(textwrap.dedent(source).strip())):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"function {name!r} not found")


def test_recover_return_union_unions_distinct_literal_branches() -> None:
    """Multiple literal return branches with distinct types union together (builtins/switch)."""
    from fangtype.inference.type_recovery import recover_return_union_from_node

    source = """
        def func(value):
            match value:
                case "a":
                    return 42
                case _:
                    return "hello"
    """
    assert recover_return_union_from_node(_func_node(source, "func")) == "int | str"


def test_recover_return_union_defers_for_single_type() -> None:
    """A single distinct literal type is not a union — defer to the existing path."""
    from fangtype.inference.type_recovery import recover_return_union_from_node

    source = """
        def func(flag):
            if flag:
                return 1
            return 2
    """
    assert recover_return_union_from_node(_func_node(source, "func")) is None


def test_recover_return_union_defers_when_any_branch_unrecovered() -> None:
    """If any return branch is not a recognized literal, defer entirely (never narrow)."""
    from fangtype.inference.type_recovery import recover_return_union_from_node

    source = """
        def func(x):
            if x > 0:
                return x
            return "Invalid input"
    """
    assert recover_return_union_from_node(_func_node(source, "func")) is None


def test_recover_return_union_defers_for_generator() -> None:
    """A generator (has yield) defers — its type is Generator[...], not a value union."""
    from fangtype.inference.type_recovery import recover_return_union_from_node

    source = """
        def gen(n):
            if n:
                return 1
            yield "x"
    """
    assert recover_return_union_from_node(_func_node(source, "gen")) is None


def test_recover_return_union_defers_for_bare_return_branch() -> None:
    """A bare ``return`` alongside a literal is partial knowledge — defer."""
    from fangtype.inference.type_recovery import recover_return_union_from_node

    source = """
        def func(flag):
            if flag:
                return "x"
            return
    """
    assert recover_return_union_from_node(_func_node(source, "func")) is None


def test_recover_return_union_ignores_nested_function_returns() -> None:
    """A nested function's returns must not contribute to the outer union."""
    from fangtype.inference.type_recovery import recover_return_union_from_node

    source = """
        def outer(flag):
            def inner():
                return 5

            if flag:
                return "a"
            return "b"
    """
    # Outer's own returns are both str -> single type -> defer (not "int | str").
    assert recover_return_union_from_node(_func_node(source, "outer")) is None
