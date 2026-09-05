"""Protocol for type validation engines."""

from typing import Protocol, runtime_checkable

from fangtype.validation import MypyDiagnostic


@runtime_checkable
class TypeValidatorProtocol(Protocol):
    """Async interface for mypy-based type validation (impl: MypyTypeValidator)."""

    async def validate_file_full(self, source: str) -> list[MypyDiagnostic]:
        """Run mypy on the entire source and return all diagnostics."""
        ...

    def close(self) -> None:
        """Release any long-lived resources held by the validator."""
        ...
