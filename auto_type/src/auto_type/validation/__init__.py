"""Validation module for auto-type."""

from auto_type.validation.mypy_diagnostic import MypyDiagnostic
from auto_type.validation.mypy_validator import MypyTypeValidator

__all__: list[str] = ["MypyDiagnostic", "MypyTypeValidator"]
