from dataclasses import dataclass


@dataclass
class MypyDiagnostic:
    """Structured mypy error (error, warning, or note) for diagnostic reporting."""

    line: int  # 1-based (from mypy)
    column: int  # 0-based (from mypy, if available)
    message: str
    error_code: str | None  # e.g., "assignment", "arg-type", "return-value"
    severity: str  # "error", "warning", "note"
