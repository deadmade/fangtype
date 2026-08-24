"""create_variable_target forwards import_hint onto the InsertionTarget (default None)."""

from fangtype.insertion.target_factory import create_variable_target


def test_default_hint_is_none() -> None:
    t = create_variable_target("x", "int", 1)
    assert t.import_hint is None


def test_hint_forwarded() -> None:
    t = create_variable_target("m", "Decimal", 4, import_hint=("decimal", "Decimal"))
    assert t.import_hint == ("decimal", "Decimal")
