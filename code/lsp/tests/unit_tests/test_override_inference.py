"""Tests for inherited-signature (override) inference of method params and returns."""

from __future__ import annotations

import ast
import textwrap

from fangtype.analysis import TypeSource
from fangtype.analysis.types import Scope, ScopeType, TypeInfo
from fangtype.inference.override_inference import (
    _apply_signature,
    _BaseSignature,
    _parse_signature,
)


def _scope(result, qualified_name: str):
    scope = result.scope_tree.get_function_scope_by_qualified_name(qualified_name)
    assert scope is not None, f"scope {qualified_name} not found"
    return scope


def test_param_inherited_from_annotated_base_in_same_file(engine) -> None:
    source = textwrap.dedent(
        """
        class Base:
            def handle(self, item: int) -> str:
                raise NotImplementedError

        class Sub(Base):
            def handle(self, item):
                return "x"
        """
    )
    result = engine.infer_types(source)

    scope = _scope(result, "Sub.handle")
    assert scope.parameters["item"].type_str == "int"
    assert scope.parameters["item"].source == TypeSource.INHERITED


def test_param_matched_positionally_when_names_differ(engine) -> None:
    source = textwrap.dedent(
        """
        class Base:
            def visit(self, t: float) -> None:
                raise NotImplementedError

        class Sub(Base):
            def visit(self, node):
                pass
        """
    )
    result = engine.infer_types(source)

    scope = _scope(result, "Sub.visit")
    assert scope.parameters["node"].type_str == "float"


def test_typevar_substitution_from_generic_base(engine) -> None:
    source = textwrap.dedent(
        """
        from typing import Generic, TypeVar

        T = TypeVar("T")

        class Visitor(Generic[T]):
            def visit(self, node: int) -> T:
                raise NotImplementedError

        class StrVisitor(Visitor[str]):
            def visit(self, node):
                return self.helper(node)
        """
    )
    result = engine.infer_types(source)

    scope = _scope(result, "StrVisitor.visit")
    assert scope.parameters["node"].type_str == "int"
    assert scope.return_type is not None
    assert scope.return_type.type_str == "str"


def test_none_default_composes_optional_with_base_annotation(engine) -> None:
    source = textwrap.dedent(
        """
        class Base:
            def go(self, x: int) -> None:
                raise NotImplementedError

        class Sub(Base):
            def go(self, x=None):
                pass
        """
    )
    result = engine.infer_types(source)

    scope = _scope(result, "Sub.go")
    assert scope.parameters["x"].type_str == "int | None"


def test_param_inherited_from_annotated_base_in_other_module(engine, tmp_path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "base.py").write_text(
        textwrap.dedent(
            """
            class Base:
                def handle(self, item: dict[str, int]) -> None:
                    raise NotImplementedError
            """
        )
    )
    sub_source = textwrap.dedent(
        """
        from pkg.base import Base

        class Sub(Base):
            def handle(self, item):
                pass
        """
    )
    sub_file = pkg / "sub.py"
    sub_file.write_text(sub_source)

    result = engine.infer_types(sub_source, path=str(sub_file), project_root=str(tmp_path))

    scope = _scope(result, "Sub.handle")
    assert scope.parameters["item"].type_str == "dict[str, int]"


def test_functions_without_base_are_untouched(engine) -> None:
    source = textwrap.dedent(
        """
        def standalone(value):
            return value
        """
    )
    result = engine.infer_types(source)

    scope = _scope(result, "standalone")
    assert scope.parameters["value"].source != TypeSource.INHERITED


def test_bare_callable_return_parameterized_from_base_signature(engine) -> None:
    """Base's parameterized ``Callable[[int], str] | None`` replaces Jedi's bare ``Callable``."""
    source = textwrap.dedent(
        """
        from typing import Callable

        class Base:
            def get_hook(self, fullname: str) -> Callable[[int], str] | None:
                raise NotImplementedError

        class Sub(Base):
            def get_hook(self, fullname):
                def hook(x):
                    return str(x)
                return hook
        """
    )
    result = engine.infer_types(source)

    scope = _scope(result, "Sub.get_hook")
    assert scope.return_type is not None
    assert scope.return_type.type_str == "Callable[[int], str] | None"
    assert scope.return_type.source == TypeSource.INHERITED


def test_bare_callable_return_unchanged_when_no_base_resolvable(engine) -> None:
    """Regression: bare ``Callable`` stays as-is when no base signature parameterizes it."""
    source = textwrap.dedent(
        """
        class Standalone:
            def get_hook(self, fullname):
                def hook(x):
                    return str(x)
                return hook
        """
    )
    result = engine.infer_types(source)

    scope = _scope(result, "Standalone.get_hook")
    assert scope.return_type is not None
    assert scope.return_type.type_str == "Callable"
    assert scope.return_type.source != TypeSource.INHERITED


def test_apply_signature_does_not_overwrite_parameterized_callable() -> None:
    """Regression: an already-parameterized ``Callable[...]`` return is never clobbered."""
    func_node = ast.parse("def get_hook(self, fullname):\n    pass\n").body[0]
    assert isinstance(func_node, ast.FunctionDef)
    func_scope = Scope(
        scope_id="func:test.get_hook",
        scope_type=ScopeType.FUNCTION,
        name="get_hook",
        ast_node=func_node,
    )
    func_scope.return_type = TypeInfo(
        type_str="Callable[[int], str]",
        source=TypeSource.RETURN_VALUE,
        line=0,
        col=0,
    )
    signature = _BaseSignature(
        params=[("self", None), ("fullname", "str")],
        return_annotation="Callable[[bool], str] | None",
    )

    _apply_signature(func_scope, func_node, signature, [])

    assert func_scope.return_type.type_str == "Callable[[int], str]"
    assert func_scope.return_type.source == TypeSource.RETURN_VALUE


def test_kwonly_param_not_annotated_from_unrelated_base_positional() -> None:
    """Bug #4 regression: a kwonly param is never annotated from a non-matching base positional."""
    func_node = ast.parse("def foo(self, a, *, extra):\n    pass\n").body[0]
    assert isinstance(func_node, ast.FunctionDef)
    func_scope = Scope(
        scope_id="func:test.foo",
        scope_type=ScopeType.FUNCTION,
        name="foo",
        ast_node=func_node,
    )
    signature = _BaseSignature(
        params=[("self", None), ("a", "int"), ("b", "str")],
        return_annotation=None,
    )

    _apply_signature(func_scope, func_node, signature, [])

    assert "extra" not in func_scope.parameters or func_scope.parameters["extra"].type_str != "str"
    assert func_scope.parameters["a"].type_str == "int"


def test_typeshed_typevar_never_reaches_a_real_subclass_override(engine) -> None:
    """H6 regression, real typeshed: list.pop's hint returns _T, undefined in the user's file."""
    source = textwrap.dedent(
        """
        class MyStack(list):
            def pop(self, index=-1):
                return super().pop(index)
        """
    )
    result = engine.infer_types(source)

    scope = _scope(result, "MyStack.pop")
    assert scope.return_type is not None
    assert "_T" not in scope.return_type.type_str


def _bare_scope(src: str, name: str) -> tuple[ast.FunctionDef, Scope]:
    func_node = ast.parse(src).body[0]
    assert isinstance(func_node, ast.FunctionDef)
    return func_node, Scope(
        scope_id=f"func:test.{name}",
        scope_type=ScopeType.FUNCTION,
        name=name,
        ast_node=func_node,
    )


def test_unsubstituted_typevar_return_is_dropped_not_inserted() -> None:
    """H6 regression: an unbound base typevar is undefined in the user's file -- never adopt it."""
    func_node, func_scope = _bare_scope("def __getitem__(self, i):\n    pass\n", "__getitem__")
    signature = _BaseSignature(params=[("self", None), ("i", "int")], return_annotation="_T")

    _apply_signature(func_scope, func_node, signature, [])

    assert func_scope.return_type is None
    assert func_scope.parameters["i"].type_str == "int"


def test_typevar_params_of_multi_arg_base_are_dropped() -> None:
    """H6 regression: _KT/_VT are not substituted by the single-arg rule, so they must not leak."""
    func_node, func_scope = _bare_scope("def get(self, key, default):\n    pass\n", "get")
    signature = _BaseSignature(
        params=[("self", None), ("key", "_KT"), ("default", "_VT")],
        return_annotation="_VT",
    )

    _apply_signature(func_scope, func_node, signature, ["str", "int"])

    assert "key" not in func_scope.parameters
    assert "default" not in func_scope.parameters
    assert func_scope.return_type is None


def test_typevar_nested_in_compound_annotation_is_dropped() -> None:
    """H6 regression: a typevar inside list[_T] leaks just as a bare _T does."""
    func_node, func_scope = _bare_scope("def items(self):\n    pass\n", "items")
    signature = _BaseSignature(params=[("self", None)], return_annotation="list[_T]")

    _apply_signature(func_scope, func_node, signature, [])

    assert func_scope.return_type is None


def test_ordinary_private_base_class_annotation_is_kept() -> None:
    """A _-prefixed real class is not a typevar -- the drop guard must not eat it."""
    func_node, func_scope = _bare_scope("def visit(self, node):\n    pass\n", "visit")
    signature = _BaseSignature(
        params=[("self", None), ("node", "_Helper")], return_annotation="list[_Helper]"
    )

    _apply_signature(func_scope, func_node, signature, [])

    assert func_scope.parameters["node"].type_str == "_Helper"
    assert func_scope.return_type is not None
    assert func_scope.return_type.type_str == "list[_Helper]"


def test_parse_signature_records_positional_boundary_excluding_kwonly() -> None:
    """L13: num_positional counts posonly+regular only, so base kwonly stay out of the index."""
    signature = _parse_signature("f(self, a: int, *, b: str) -> None")
    assert signature is not None
    assert signature.num_positional == 2  # self, a -- b is keyword-only
    assert signature.params == [("self", None), ("a", "int"), ("b", "str")]


def test_override_positional_param_not_typed_from_base_kwonly_by_index() -> None:
    """L13 regression: an override positional param must not adopt a base kwonly param by index."""
    func_node = ast.parse("def f(self, x, y):\n    pass\n").body[0]
    assert isinstance(func_node, ast.FunctionDef)
    func_scope = Scope(
        scope_id="func:test.f",
        scope_type=ScopeType.FUNCTION,
        name="f",
        ast_node=func_node,
    )
    # Base ``def f(self, a, *, b: str)`` -- ``b`` sits at flattened index 2 but is keyword-only.
    signature = _BaseSignature(
        params=[("self", None), ("a", None), ("b", "str")],
        return_annotation=None,
        num_positional=2,
    )

    _apply_signature(func_scope, func_node, signature, [])

    # ``y`` is positional index 2; without the boundary it would wrongly become ``str``.
    assert "y" not in func_scope.parameters or func_scope.parameters["y"].type_str != "str"


def test_kwonly_param_still_resolves_by_matching_base_kwonly_name() -> None:
    """A kwonly param still resolves by name against a matching base kwonly param."""
    func_node = ast.parse("def foo(self, a, *, extra):\n    pass\n").body[0]
    assert isinstance(func_node, ast.FunctionDef)
    func_scope = Scope(
        scope_id="func:test.foo",
        scope_type=ScopeType.FUNCTION,
        name="foo",
        ast_node=func_node,
    )
    signature = _BaseSignature(
        params=[("self", None), ("a", "int"), ("extra", "bool")],
        return_annotation=None,
    )

    _apply_signature(func_scope, func_node, signature, [])

    assert func_scope.parameters["extra"].type_str == "bool"
