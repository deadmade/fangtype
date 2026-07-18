"""Tests for Jedi type formatting, focused on parameterized-generic recovery."""

from __future__ import annotations

from typing import Any

from fangtype.inference.jedi.type_formatter import (
    extract_type_hint,
    format_jedi_type,
    infer_return_type,
)


class FakeJediType:
    """Minimal stand-in for the Jedi Name/Value interface used by the formatter."""

    def __init__(
        self,
        name: str,
        *,
        module_name: str = "builtins",
        type_hint: str | None = None,
        hint_error: Exception | None = None,
        type_: str = "instance",
        infer_result: list[Any] | None = None,
    ) -> None:
        self.name = name
        self.module_name = module_name
        self._type_hint = type_hint
        self._hint_error = hint_error
        self.type = type_
        self._infer_result = infer_result or []
        self.get_type_hint_calls = 0

    def get_type_hint(self) -> str | None:
        self.get_type_hint_calls += 1
        if self._hint_error is not None:
            raise self._hint_error
        return self._type_hint

    def infer(self) -> list[Any]:
        return self._infer_result

    def execute(self) -> list[Any]:
        return self._infer_result


def test_container_builtin_uses_parameterized_type_hint() -> None:
    t = FakeJediType("list", type_hint="list[SymbolSnapshot]")
    assert format_jedi_type(t) == "list[SymbolSnapshot]"


def test_container_builtin_normalizes_typing_hint() -> None:
    assert format_jedi_type(FakeJediType("list", type_hint="List[int]")) == "list[int]"
    assert format_jedi_type(FakeJediType("dict", type_hint="dict[str, int]")) == "dict[str, int]"
    assert format_jedi_type(FakeJediType("tuple", type_hint="tuple[int, str]")) == "tuple[int, str]"


def test_container_builtin_falls_back_to_bare_when_hint_empty() -> None:
    assert format_jedi_type(FakeJediType("list", type_hint="")) == "list"
    assert format_jedi_type(FakeJediType("dict", type_hint=None)) == "dict"


def test_container_builtin_falls_back_to_bare_on_any_hint_error() -> None:
    # A broadened guard must survive any unexpected error from Jedi's generics machinery.
    for err in (AttributeError(), TypeError(), ValueError("boom")):
        assert format_jedi_type(FakeJediType("list", hint_error=err)) == "list"


def test_non_container_builtin_short_circuits_without_type_hint() -> None:
    t = FakeJediType("int", type_hint="junk")
    assert format_jedi_type(t) == "int"
    assert t.get_type_hint_calls == 0  # never consulted for scalars


def test_infer_return_type_parameterizes_builtin_return() -> None:
    rv = FakeJediType("list", type_hint="list[int]")
    func = FakeJediType("f", module_name="mymod", infer_result=[rv])
    assert infer_return_type(func) == "list[int]"


def test_infer_return_type_keeps_none_member_in_union() -> None:
    # `X | None` returns must not collapse to bare `X`.
    rv_str = FakeJediType("str")
    rv_none = FakeJediType("NoneType")
    func = FakeJediType("f", module_name="mymod", infer_result=[rv_str, rv_none])
    assert infer_return_type(func) == "str | None"


def test_plain_function_builtin_name_rejected_without_type_hint() -> None:
    # `isinstance` is the builtin function, not a class -- its bare name isn't a type annotation.
    t = FakeJediType("isinstance", type_="function", type_hint=None)
    assert format_jedi_type(t) == "Unknown"


def test_plain_function_call_signature_hint_rejected() -> None:
    # A plain function's get_type_hint() returns a call signature, not a type expr -- reject it.
    t = FakeJediType(
        "isinstance",
        type_="function",
        module_name="builtins",
        type_hint="isinstance(obj: object, class_or_tuple: _ClassInfo, /) -> bool",
    )
    assert format_jedi_type(t) == "Unknown"


def test_class_typed_object_keeps_returning_its_name() -> None:
    # Regression: classes must keep resolving to their bare name.
    t = FakeJediType("MyClass", type_="class", module_name="mymod")
    assert format_jedi_type(t) == "MyClass"


def test_builtin_class_keeps_returning_its_name() -> None:
    # Regression: builtin classes (e.g. `int`) keep taking the early builtins short-circuit.
    t = FakeJediType("int", type_="class", type_hint="junk")
    assert format_jedi_type(t) == "int"
    assert t.get_type_hint_calls == 0


def test_function_with_callable_type_hint_keeps_hint() -> None:
    # Regression: a function object yielding a genuine Callable[...] hint must keep using it.
    t = FakeJediType(
        "some_func", type_="function", module_name="mymod", type_hint="Callable[..., bool]"
    )
    assert format_jedi_type(t) == "Callable[..., bool]"


def test_ast_return_fallback_never_downgrades_parameterized_hint() -> None:
    from fangtype.inference.jedi.scope_builder import _apply_ast_return_fallback

    # Parameterized/abstract Jedi hints survive a bare AST container observation.
    assert _apply_ast_return_fallback("Sequence[int]", "list") == "Sequence[int]"
    assert _apply_ast_return_fallback("list[int]", "list") == "list[int]"
    # AST fills genuine gaps and still corrects bare-vs-bare disagreements.
    assert _apply_ast_return_fallback("Unknown", "list") == "list"
    assert _apply_ast_return_fallback("str", "list") == "list"
    assert _apply_ast_return_fallback("dict", None) == "dict"


def test_extract_type_hint_unknown_fallback_returns_none() -> None:
    # RED case: format_jedi_type(None) == "Unknown" (truthy) must not leak out of
    # extract_type_hint, or the caller's `... or format_types(...)` fallback never runs.
    assert format_jedi_type(None) == "Unknown"

    name = FakeJediType("x", hint_error=AttributeError())
    assert extract_type_hint(name, [None]) is None


def test_extract_type_hint_returns_real_hint() -> None:
    # Regression guard: a genuine hint still comes back untouched.
    name = FakeJediType("x", type_hint="int")
    assert extract_type_hint(name, [None]) == "int"
