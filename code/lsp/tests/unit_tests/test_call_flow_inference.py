"""Tests for call-flow inference and type-update precedence rules."""

from __future__ import annotations

import ast
import textwrap

import jedi

from fangtype.analysis.types import Scope, ScopeType, TypeInfo, TypeSource
from fangtype.inference.call_flow_inference import (
    _bind_call_arguments,
    _infer_expression_type,
    _should_update,
    propagate_call_flow_types,
)
from fangtype.inference.jedi.engine import JediInferenceEngine
from fangtype.inference.jedi.scope_builder import (
    _build_call_site_index,
    _infer_local_function_return_type,
    build_scope_tree,
)
from fangtype.utils.settings import Settings


def _info(type_str: str, source: TypeSource = TypeSource.PARAMETER_USAGE) -> TypeInfo:
    return TypeInfo(type_str=type_str, source=source, line=0, col=0)


class _RecordingProbe:
    """A TypeProbe stub that records calls and returns a fixed type."""

    def __init__(self, answer: str = "Unknown") -> None:
        self.calls: list[ast.expr] = []
        self._answer = answer

    def infer_expr_type(self, expr: ast.expr) -> str:
        self.calls.append(expr)
        return self._answer


def test_propagate_accepts_a_typeprobe_and_calls_it():
    # A higher-order call whose return type is only knowable via the probe.
    source = (
        "def apply(fn):\n    return fn()\n\ndef make():\n    return 5\n\nresult = apply(make)\n"
    )
    tree = ast.parse(source)

    script = jedi.Script(code=source)
    scope_tree = build_scope_tree(script, tree)

    # Clear make's resolved return type to force positional-inference fallback (TypeProbe seam).
    make_scope = next(
        scope
        for scope in scope_tree.get_all_function_scopes()
        if scope.get_qualified_name() == "make"
    )
    make_scope.return_type = None

    probe = _RecordingProbe(answer="Unknown")
    # Must accept a TypeProbe (not a jedi.Script) and invoke it.
    propagate_call_flow_types(tree, scope_tree, probe)
    assert probe.calls, "propagate_call_flow_types must query the probe"


def test_ellipsis_constant_is_not_inferred_as_undefined_name() -> None:
    """L10: `...` must not become the annotation string 'ellipsis' (a valid-looking undefined name)."""
    expr = ast.parse("...", mode="eval").body
    scope = Scope(
        scope_id="module",
        scope_type=ScopeType.MODULE,
        name="<module>",
        ast_node=ast.parse(""),
    )
    result = _infer_expression_type(expr, scope, _RecordingProbe(), {}, {}, {}, {})
    assert result == ""


def test_should_update_replaces_any():
    assert _should_update(_info("Any"), "str") is True


def test_should_update_still_refuses_literal():
    assert _should_update(_info("int", TypeSource.LITERAL), "str") is False


def test_update_allows_parameterizing_a_bare_container() -> None:
    assert _should_update(_info("list"), "list[str]") is True


def test_update_rejects_longer_but_unrelated_type() -> None:
    # "Longer string wins" is not a type-refinement relation.
    assert _should_update(_info("int"), "SomeVeryLongClassName") is False


def test_update_never_overwrites_inherited_contract() -> None:
    assert _should_update(_info("Instance", TypeSource.INHERITED), "list[str]") is False


def test_local_name_is_not_resolved_to_an_unrelated_method() -> None:
    """A plain `size` must not suffix-match the unrelated method `Config.size` (was: Callable)."""
    source = textwrap.dedent(
        """
        class Config:
            def size(self):
                return 3


        def render(width):
            pass


        def main(size):
            render(size)
        """
    )
    result = JediInferenceEngine(Settings()).infer_types(source)
    scope = result.scope_tree.get_function_scope_by_qualified_name("render")
    assert scope is not None
    assert scope.parameters["width"].type_str == "Unknown"


def test_mutually_recursive_local_functions_do_not_blow_the_stack() -> None:
    """`a` returns `b`, `b` returns `a`: must not RecursionError and abort the whole file."""
    source = textwrap.dedent(
        """
        def a():
            return b


        def b():
            return a


        x = a()
        """
    )
    result = JediInferenceEngine(Settings()).infer_types(source)
    assert result.is_complete is True


def test_non_cyclic_local_return_chain_still_resolves() -> None:
    """One-hop bare-name return chaining must keep working after the cycle guard.

    `g` returns the bare name `h` (not a call), so resolving `g`'s "return type"
    recurses through `_infer_local_function_return_type`'s `isinstance(stmt.value,
    ast.Name)` branch into `h`'s own `return 5`. That is the exact branch the P1
    cycle guard (the `seen` set) wraps around; a `def g(): return h()` call-return
    chain (the previous version of this test) resolves natively through Jedi and
    never touches the guarded branch at all.

    The public `infer_types()` entry point can't observe this: Jedi's own
    inference of `g()` already succeeds (it resolves to `Callable`, since `h` is a
    real function object), so `_infer_function_call_assignments`'s AST fallback
    (line ~492) never fires for `y = g()` -- unrelated to the guard. So we assert
    directly on `_infer_local_function_return_type`, the function the guard lives
    in.
    """
    source = textwrap.dedent(
        """
        def h():
            return 5


        def g():
            return h
        """
    )
    tree = ast.parse(source)
    index = _build_call_site_index(tree)
    assert _infer_local_function_return_type(index, "g", line_0=999) == "int"


def test_none_default_param_composes_optional_from_call_sites() -> None:
    """`def f(x=None)` called with an int must become `int | None`, not `int`."""
    source = textwrap.dedent(
        """
        def f(x=None):
            return x


        f(3)
        """
    )
    result = JediInferenceEngine(Settings()).infer_types(source)
    scope = result.scope_tree.get_function_scope_by_qualified_name("f")
    assert scope is not None
    assert scope.parameters["x"].type_str == "int | None"


def _func_and_call(source: str) -> tuple[ast.FunctionDef, ast.Call]:
    tree = ast.parse(textwrap.dedent(source))
    func_node = tree.body[0]
    call_node = tree.body[1].value
    assert isinstance(func_node, ast.FunctionDef)
    assert isinstance(call_node, ast.Call)
    return func_node, call_node


def test_positional_arg_after_starred_binds_to_no_fixed_param() -> None:
    """A positional arg after `*pair` has an unknowable position; it must not mis-bind to `b`."""
    func_node, call_node = _func_and_call(
        """
        def g(a, b, c):
            pass
        g(*pair, "tail")
        """
    )
    mapping = _bind_call_arguments(func_node, call_node)
    bound_constants = {name for name, expr in mapping.items() if isinstance(expr, ast.Constant)}
    assert bound_constants == set()


def test_positional_binding_without_star_is_unaffected() -> None:
    func_node, call_node = _func_and_call(
        """
        def g(a, b, c):
            pass
        g(x, y)
        """
    )
    mapping = _bind_call_arguments(func_node, call_node)
    assert isinstance(mapping["a"], ast.Name) and mapping["a"].id == "x"
    assert isinstance(mapping["b"], ast.Name) and mapping["b"].id == "y"


def test_positional_arg_before_starred_still_binds() -> None:
    func_node, call_node = _func_and_call(
        """
        def g(a, b, c):
            pass
        g(x, *rest)
        """
    )
    mapping = _bind_call_arguments(func_node, call_node)
    assert isinstance(mapping["a"], ast.Name) and mapping["a"].id == "x"
    assert "b" not in mapping
    assert "c" not in mapping


def test_keyword_binding_past_starred_still_works() -> None:
    func_node, call_node = _func_and_call(
        """
        def g(a, b, c):
            pass
        g(*pair, c=z)
        """
    )
    mapping = _bind_call_arguments(func_node, call_node)
    assert isinstance(mapping["c"], ast.Name) and mapping["c"].id == "z"
