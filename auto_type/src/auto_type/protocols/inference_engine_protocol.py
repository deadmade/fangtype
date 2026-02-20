"""Protocol for type inference engines."""

from typing import Protocol, runtime_checkable

from auto_type.inference import InferenceResult  # noqa: TC001


@runtime_checkable
class InferenceEngineProtocol(Protocol):
    """Protocol for type inference engines.

    Defines the interface that any type inference engine must implement.
    The primary implementation is JediInferenceEngine.

    All methods are sync and execute inference inline.
    """

    def infer_types(
        self,
        source: str,
        path: str | None = None,
        project_root: str | None = None,
    ) -> InferenceResult:
        """Perform complete type inference on Python source code.

        Args:
            source: Python source code string
            path: Optional file path for project-aware inference
            project_root: Optional explicit project root path (e.g., from benchmark)

        Returns:
            InferenceResult with scope tree and inferred types
        """
        ...

    def infer_expression_type(
        self,
        source: str,
        expression: str,
        path: str | None = None,
        line_hint: int | None = None,
    ) -> str | None:
        """Infer type of any Python expression.

        Args:
            source: Original Python source code
            expression: Python expression to infer type for
            path: Optional file path for project-aware inference
            line_hint: Optional 1-based source line where expression appears

        Returns:
            Type string if inference succeeds, None otherwise
        """
        ...

    def infer_types_at_locations(
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
