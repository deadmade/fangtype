"""Protocol for type annotation workflow operations."""

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from auto_type.inference.inference_result import InferenceResult


@runtime_checkable
class TypeAnnotationWorkflowProtocol(Protocol):
    """Protocol for type annotation workflow operations.

    Defines the interface for orchestrating type inference, validation,
    and insertion workflows. The primary implementation is TypeAnnotationWorkflow.

    Most methods are async to support non-blocking operations. Methods that only
    perform fast CPU-bound operations (remove_types, preview_removals) remain sync.
    """

    async def insert_single_type(
        self,
        source: str,
        variable_name: str,
        type_annotation: str,
        line_number: int | None = None,
    ) -> tuple[str, bool, str]:
        """Insert type annotation for a single variable.

        Args:
            source: Python source code
            variable_name: Name of the variable to annotate
            type_annotation: The type string to insert
            line_number: Optional 1-based line number to target a specific assignment

        Returns:
            Tuple of (modified_source, success, message)
        """
        ...

    async def insert_all_types(
        self, source: str, file_path: str | None, skip_annotated: bool = True
    ) -> tuple[str, int, int, str]:
        """Insert all inferred types in a file.

        Args:
            source: Python source code
            file_path: Optional file path for project-aware inference
            skip_annotated: If True, skip items that already have annotations

        Returns:
            Tuple of (modified_source, var_count, func_count, message)
        """
        ...

    async def preview_insertions(self, source: str) -> dict[str, Any]:
        """Preview what type annotations would be inserted.

        Args:
            source: Python source code

        Returns:
            Dict with preview information (will_insert, will_skip, etc.)
        """
        ...

    def remove_types(
        self, source: str, variables: list[str] | None = None, include_functions: bool = False
    ) -> tuple[str, dict[str, Any]]:
        """Remove type annotations from source.

        This method is sync because it only performs fast CPU-bound operations.

        Args:
            source: Python source code
            variables: Optional list of variable names to remove annotations from
            include_functions: If True, also remove function annotations

        Returns:
            Tuple of (modified_source, result_info)
        """
        ...

    def preview_removals(self, source: str, variables: list[str] | None = None) -> dict[str, Any]:
        """Preview what type annotations would be removed.

        This method is sync because it only performs fast CPU-bound operations.

        Args:
            source: Python source code
            variables: Optional list of variable names to preview

        Returns:
            Dict with preview information
        """
        ...

    async def infer_and_collect_types(
        self, source: str, file_path: str | None
    ) -> tuple["InferenceResult", dict[str, str], dict[str, dict[str, Any]]]:
        """Run inference and collect all insertable types.

        This method is primarily for benchmarks that need access to the
        inference result and raw type dictionaries.

        Args:
            source: Python source code
            file_path: Optional file path for project-aware inference

        Returns:
            Tuple of (inference_result, module_vars, functions)
        """
        ...

    async def collect_and_validate_types(
        self, source: str, file_path: str | None
    ) -> tuple["InferenceResult", dict[str, str]]:
        """Run inference, collect types from all scopes, and validate them.

        This method performs the orchestration logic for inlay hints:
        - Phase 1: Runs inference and collects all types from all scopes
        - Phase 2: Batch validates types with mypy (if enabled)

        Args:
            source: Python source code
            file_path: Optional file path for project-aware inference

        Returns:
            Tuple of (inference_result, validated_types)
        """
        ...
