"""With an import_hint, a type Jedi named but the source doesn't import validates as valid."""

from fangtype.utils.settings import Settings
from fangtype.validation.mypy_validator import MypyTypeValidator


async def test_type_needing_import_is_valid_with_hint() -> None:
    validator = MypyTypeValidator(Settings())
    source = "x = 1\n"  # Decimal is NOT imported here
    types_map = {(1, "m"): "Decimal"}
    # Without a hint, Decimal is undefined -> invalid (the current drop behavior).
    without = await validator.validate_bulk(types_map, source)
    assert without[(1, "m")].is_valid is False
    # With the hint, the probe imports Decimal -> valid.
    hints = {(1, "m"): ("decimal", "Decimal")}
    withh = await validator.validate_bulk(types_map, source, import_hints=hints)
    assert withh[(1, "m")].is_valid is True
