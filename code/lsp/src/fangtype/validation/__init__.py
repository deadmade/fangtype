"""Validation module for fangtype."""

from fangtype.validation.mypy_diagnostic import MypyDiagnostic
from fangtype.validation.mypy_validator import MypyTypeValidator

__all__: list[str] = ["MypyDiagnostic", "MypyTypeValidator"]
