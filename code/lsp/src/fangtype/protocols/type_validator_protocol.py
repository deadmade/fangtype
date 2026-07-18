"""Protocol for type validation engines."""

from typing import Protocol, TypeVar, runtime_checkable

from fangtype.validation import MypyDiagnostic
from fangtype.validation.mypy_validator import TypeValidationResult

# Generic bulk-validation key; caller's key type (str or tuple[int, str]) survives to the result.
_KeyT = TypeVar("_KeyT")


@runtime_checkable
class TypeValidatorProtocol(Protocol):
    """Async interface for mypy-based type validation (impl: MypyTypeValidator)."""

    async def validate_bulk(
        self, types_map: dict[_KeyT, str], source: str
    ) -> dict[_KeyT, TypeValidationResult]:
        """Validate a {key: type_str} map against source, returning {key: TypeValidationResult}."""
        ...

    async def validate_file_full(self, source: str) -> list[MypyDiagnostic]:
        """Run mypy on the entire source and return all diagnostics."""
        ...

    def close(self) -> None:
        """Release any long-lived resources held by the validator."""
        ...
