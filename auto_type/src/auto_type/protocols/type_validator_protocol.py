"""Protocol for type validation engines."""

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from auto_type.validation.mypy_validator import MypyDiagnostic


@runtime_checkable
class TypeValidatorProtocol(Protocol):
    """Protocol for type validation engines.

    Defines the interface for validating type annotations using mypy.
    The primary implementation is MypyTypeValidator.

    All methods are async to support non-blocking validation.
    """

    async def validate(self, type_str: str, source: str) -> bool:
        """Validate a single type string using mypy.

        Args:
            type_str: Type annotation to validate
            source: Full source code for context

        Returns:
            True if type is valid according to mypy, False otherwise
        """
        ...

    async def validate_bulk(
        self, types_map: dict[Any, str], source: str, timeout: float = 30.0
    ) -> dict[Any, str]:
        """Validate multiple types at once.

        Args:
            types_map: Dict of {key: type_str} to validate. Key can be str or tuple.
            source: Full source code for context
            timeout: Maximum time to wait for validation

        Returns:
            Dict of {key: type_str} containing only valid types
        """
        ...

    async def validate_insertion(
        self, source: str, variable_name: str, type_annotation: str
    ) -> tuple[bool, str]:
        """Validate a type annotation before insertion.

        Args:
            source: Source code where the type will be inserted
            variable_name: Name of the variable being annotated
            type_annotation: Type annotation to validate

        Returns:
            Tuple of (is_valid, error_message). error_message is empty if valid.
        """
        ...

    async def validate_file_full(
        self, source: str, timeout: float = 30.0
    ) -> list["MypyDiagnostic"]:
        """Run mypy on entire file and return ALL errors/warnings.

        Args:
            source: Complete Python source code
            timeout: Maximum time to wait for validation

        Returns:
            List of structured mypy diagnostics
        """
        ...
