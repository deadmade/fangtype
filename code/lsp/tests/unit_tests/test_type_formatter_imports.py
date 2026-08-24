"""Tests for resolve_import: deriving (module, name) imports from Jedi objects."""

from pathlib import Path
from types import SimpleNamespace

from fangtype.inference.jedi.type_formatter import resolve_import
from fangtype.inference.type_utils import import_for_annotation

# Stands in for "defined somewhere other than the file being annotated". Defaulting to it
# keeps every case below about full_name alone, so the locality cases have to name a path.
_ELSEWHERE = Path("/elsewhere/mod.pyi")


def _jedi(
    name: str, full_name: str | None, module_path: Path | None = _ELSEWHERE
) -> SimpleNamespace:
    # Mimics the three attributes resolve_import reads off a Jedi Name/type object.
    return SimpleNamespace(name=name, full_name=full_name, module_path=module_path)


def test_resolve_stdlib_type() -> None:
    assert resolve_import(_jedi("Decimal", "decimal.Decimal")) == ("decimal", "Decimal")


def test_resolve_nested_module() -> None:
    assert resolve_import(_jedi("deque", "collections.deque")) == ("collections", "deque")


def test_builtin_returns_none() -> None:
    assert resolve_import(_jedi("int", "builtins.int")) is None


def test_missing_full_name_returns_none() -> None:
    assert resolve_import(_jedi("Foo", None)) is None
    assert resolve_import(_jedi("Foo", "")) is None


def test_last_component_mismatch_returns_none() -> None:
    # Defensive: bare name must be the final dotted component.
    assert resolve_import(_jedi("Decimal", "decimal.Other")) is None


def test_bare_full_name_returns_none() -> None:
    # No module part to import from.
    assert resolve_import(_jedi("Foo", "Foo")) is None


def test_none_object_returns_none() -> None:
    assert resolve_import(None) is None


def test_symbol_defined_in_the_annotated_module_returns_none() -> None:
    # A class defined in the file being annotated needs no import, and writing one produces
    # a module that imports itself.
    own = Path("/proj/realmod.py")
    assert resolve_import(_jedi("Node", "realmod.Node", own), own) is None


def test_in_memory_module_symbol_returns_none() -> None:
    # Jedi calls a pathless module __main__ and reports module_path None. Both sides being
    # None is the in-memory case, and it is still the module under analysis.
    assert resolve_import(_jedi("Node", "__main__.Node", None), None) is None


def test_relative_own_path_still_matches_absolute_module_path() -> None:
    own = Path("realmod.py")
    resolved = own.resolve()
    assert resolve_import(_jedi("Node", "realmod.Node", resolved), own) is None


def test_symbol_from_another_module_keeps_its_hint() -> None:
    assert resolve_import(
        _jedi("Decimal", "decimal.Decimal", Path("/usr/lib/decimal.pyi")),
        Path("/proj/realmod.py"),
    ) == ("decimal", "Decimal")


def test_unknown_own_path_keeps_the_hint_for_an_on_disk_symbol() -> None:
    # own_module_path defaults to None; a symbol with a real module_path is not local to it.
    assert resolve_import(_jedi("Decimal", "decimal.Decimal", Path("/usr/lib/decimal.pyi"))) == (
        "decimal",
        "Decimal",
    )


def test_hint_for_a_different_symbol_than_the_annotation_is_dropped() -> None:
    """A hint whose name the annotation never mentions describes the wrong symbol.

    Emitting it writes an import nothing in the file uses. Checked here with an annotation
    outside the synthesised table, so it is the mention test doing the work and not the table.
    """
    assert resolve_import(_jedi("loads", "json.loads"), None, "Foo") is None


def test_hint_survives_inside_a_union_or_a_generic() -> None:
    """The bare name has to be mentioned by the annotation, not equal to it."""
    assert resolve_import(_jedi("Decimal", "decimal.Decimal"), None, "Decimal | None") == (
        "decimal",
        "Decimal",
    )
    assert resolve_import(_jedi("Decimal", "decimal.Decimal"), None, "list[Decimal]") == (
        "decimal",
        "Decimal",
    )


def test_partial_name_match_does_not_keep_a_hint() -> None:
    assert resolve_import(_jedi("Node", "mod.Node"), None, "NodeList") is None


def test_synthesised_callable_gets_its_own_import() -> None:
    """`Callable` is synthesised by the formatter, so no Jedi object can supply its import.

    `load = json.loads` is the running example's case: Jedi resolves `json.loads`, the
    annotation settled on is `Callable`, and the import that has to be written is neither
    derivable from the former nor optional for the latter.
    """
    assert resolve_import(_jedi("loads", "json.loads"), None, "Callable") == (
        "collections.abc",
        "Callable",
    )
    assert import_for_annotation("Callable") == ("collections.abc", "Callable")
    assert import_for_annotation("Callable | None") == ("collections.abc", "Callable")
    assert import_for_annotation("int") is None
