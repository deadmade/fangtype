"""Protocol for type validation engines."""

from typing import Any, Protocol, runtime_checkable

from auto_type.validation import MypyDiagnostic  # noqa: TC001
from auto_type.validation.mypy_validator import TypeValidationResult  # noqa: TC001


@runtime_checkable
class TypeValidatorProtocol(Protocol):
    """Protocol for type validation engines.

    Defines the interface for validating type annotations using mypy.
    The primary implementation is MypyTypeValidator.

    All methods are async to support non-blocking validation.
    """

    async def validate_bulk(
        self, types_map: dict[Any, str], source: str
    ) -> dict[Any, TypeValidationResult]:
        """Validate multiple types at once.

        Args:
            types_map: Dict of {key: type_str} to validate. Key can be str or tuple.
            source: Full source code for context
        Returns:
            Dict of {key: TypeValidationResult} containing validation status.
        """
        ...

    async def validate_file_full(self, source: str) -> list[MypyDiagnostic]:
        """Run mypy on entire file and return ALL errors/warnings.

        Args:
            source: Complete Python source code
        Returns:
            List of structured mypy diagnostics
        """
        ...
