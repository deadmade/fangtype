"""Protocol for type inference engines."""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from auto_type.inference.inference_result import InferenceResult


@runtime_checkable
class InferenceEngineProtocol(Protocol):
    """Protocol for type inference engines.

    Defines the interface that any type inference engine must implement.
    The primary implementation is JediInferenceEngine.

    All methods are async to support non-blocking inference.
    """

    async def infer_types(self, source: str, path: str | None = None) -> "InferenceResult":
        """Perform complete type inference on Python source code.

        Args:
            source: Python source code string
            path: Optional file path for project-aware inference

        Returns:
            InferenceResult with scope tree and inferred types
        """
        ...

    async def infer_variable_types(self, source: str) -> dict[str, str]:
        """Get module-level variable types.

        Args:
            source: Python source code

        Returns:
            Dict mapping variable names to type strings (module-level only)
        """
        ...

    async def infer_expression_type(self, source: str, expression: str) -> str | None:
        """Infer type of any Python expression.

        Args:
            source: Original Python source code
            expression: Python expression to infer type for

        Returns:
            Type string if inference succeeds, None otherwise
        """
        ...

    async def infer_types_at_locations(
        self,
        source: str,
        locations: list[tuple[int, int]],
        path: str | None = None,
    ) -> dict[tuple[int, int], str]:
        """Infer types at multiple specific locations in the source code.

        Args:
            source: Python source code string
            locations: List of (line, col) tuples where line is 1-based
            path: Optional file path for project-aware inference

        Returns:
            Dict mapping (line, col) to inferred type string
        """
        ...
