from collections.abc import Hashable
from dataclasses import dataclass


@dataclass
class MypyDiagnostic:
    """Structured mypy error for diagnostic reporting.

    Represents a single error, warning, or note from mypy analysis.
    """

    line: int  # 1-based (from mypy)
    column: int  # 0-based (from mypy, if available)
    end_column: int | None  # For ranges, if available
    message: str
    error_code: str | None  # e.g., "assignment", "arg-type", "return-value"
    severity: str  # "error", "warning", "note"
    key: Hashable | None = None
    type_str: str | None = None
    is_valid: bool | None = None
