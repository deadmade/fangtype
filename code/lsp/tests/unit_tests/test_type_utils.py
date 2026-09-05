import pytest

from fangtype.inference.type_utils import (
    import_for_annotation,
    normalize_type_name,
    simplify_union_type,
)


def test_any_absorbs_union_members():
    assert normalize_type_name("int | Any") == "Any"
    assert normalize_type_name("None | Any") == "Any"
    assert normalize_type_name("str | Any") == "Any"
    assert normalize_type_name("Any | None") == "Any"
    assert normalize_type_name("Optional[Any]") == "Any"


def test_plain_union_preserved():
    assert normalize_type_name("int | None") == "int | None"
    assert normalize_type_name("int | str") == "int | str"


def test_nested_union_not_split_at_top_level():
    assert normalize_type_name("dict[str, int | None]") == "dict[str, int | None]"


def test_top_level_union_with_generic_member():
    assert normalize_type_name("int | list[str]") == "int | list[str]"
    # Top-level-union bug: generic branch misparses "int | List" and never lowercases List.
    assert normalize_type_name("int | List[str]") == "int | list[str]"


def test_simplify_union_dedups():
    assert simplify_union_type("int | int") == "int"


def test_regression_legacy_normalization_unchanged():
    assert normalize_type_name("List[int]") == "list[int]"
    assert normalize_type_name("Optional[int]") == "int | None"
    assert normalize_type_name("Union[int, str]") == "int | str"


@pytest.mark.parametrize(
    "original,expected",
    [
        ("Dict[str, Any]", "dict[str, Any]"),
        ("Union[str, None]", "str | None"),
        ("Tuple[int, str]", "tuple[int, str]"),
        ("Set[int]", "set[int]"),
        ("param_func() -> str", "Callable"),
        ("<lambda>(x) -> int", "Callable"),
        ("func2(self: MyClass, a)", "Callable"),
        ("int)", "int"),
        # FunctionType and GeneratorType are rewritten to their collections.abc spellings,
        # which is what makes them importable. CodeType has no such counterpart and still
        # passes through. An already-parameterised Generator[...] is left alone.
        ("GeneratorType", "Generator"),
        ("CodeType", "CodeType"),
        ("GeneratorType | None", "Generator | None"),
        ("Generator[int, None, None]", "Generator[int, None, None]"),
    ],
)
def test_normalize_type_name(original, expected):
    """Legacy typing normalization plus call-signature/malformed collapse."""
    assert normalize_type_name(original) == expected


def test_empty_subscript_repaired_to_bare_base():
    """2a: an empty subscript like ``tuple[]`` recovers to the bare base type."""
    assert normalize_type_name("tuple[]") == "tuple"
    assert normalize_type_name("list[]") == "list"


def test_unrepairable_garbage_becomes_unknown():
    """2b: syntactically-invalid Jedi garbage collapses to the "Unknown" sentinel."""
    garbage = "None, erase_meta_id(id)]], replacement: Union[AnyType, AnyType])"
    assert normalize_type_name(garbage) == "Unknown"


@pytest.mark.parametrize(
    "original",
    [
        "list[str]",
        "dict[str, int]",
        "int | None",
        "Callable[..., int]",
        "tuple",
        "Foo",
        "mod.Bar",
    ],
)
def test_valid_annotations_round_trip_unchanged(original):
    """The validity gate must not touch any real, syntactically-valid annotation."""
    assert normalize_type_name(original) == original


def test_optional_still_normalizes_through_the_gate():
    assert normalize_type_name("Optional[int]") == "int | None"


def test_nested_generic_round_trips_unchanged():
    assert normalize_type_name("dict[str, list[int]]") == "dict[str, list[int]]"


def test_empty_and_whitespace_input_pass_through_unchanged():
    """Empty/whitespace-only input must pass through unchanged, not be gated to "Unknown"."""
    assert normalize_type_name("") == ""
    assert normalize_type_name("   ") == "   "

    # Contrast: a genuinely-invalid *non-empty* string still gates to "Unknown".
    assert normalize_type_name("(") == "Unknown"


def test_runtime_function_class_normalizes_to_callable():
    """Jedi spells a function-valued element `FunctionType`, which names no importable symbol here.

    Left alone it is a syntactically valid expression, so it survives the validity gate and
    reaches mypy as an undefined name. `Callable` is the spelling the rest of the pipeline
    already knows how to import.
    """
    assert normalize_type_name("FunctionType") == "Callable"
    assert normalize_type_name("dict[str, FunctionType]") == "dict[str, Callable]"
    assert normalize_type_name("list[FunctionType]") == "list[Callable]"


def test_runtime_generator_class_normalizes_to_generator():
    assert normalize_type_name("GeneratorType") == "Generator"
    assert normalize_type_name("list[GeneratorType]") == "list[Generator]"


def test_synthesised_names_carry_their_import():
    assert import_for_annotation("dict[str, Callable]") == ("collections.abc", "Callable")
    assert import_for_annotation("Generator") == ("collections.abc", "Generator")
    assert import_for_annotation("int") is None
