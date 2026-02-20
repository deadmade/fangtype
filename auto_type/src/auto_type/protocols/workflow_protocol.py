"""Protocol for type annotation workflow operations."""

from typing import Any, Protocol, runtime_checkable

from auto_type.inference import InferenceResult  # noqa: TC001
from auto_type.validation.mypy_validator import TypeValidationResult  # noqa: TC001


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

    async def annotate_target_with_fallbacks(
        self,
        source: str,
        file_path: str | None,
        line_number: int,
        annotation_type: str,
        variable_name: str | None = None,
        function_name: str | None = None,
        parameter_name: str | None = None,
        project_root: str | None = None,
    ) -> dict[str, Any]:
        """Infer and insert one annotation target with production fallbacks.

        Args:
            source: Python source code
            file_path: Optional file path for project-aware inference
            line_number: 1-based target line from caller context
            annotation_type: Target category string
            variable_name: Variable/expression target name when applicable
            function_name: Function name for function targets
            parameter_name: Parameter name for function parameter targets
            project_root: Optional explicit project root

        Returns:
            Dict containing at minimum:
            - inferred_type: str | None
            - modified_source: str
            - insertion_success: bool
            - error_message: str | None
        """
        ...

    async def insert_all_types(
        self,
        source: str,
        file_path: str | None,
        skip_annotated: bool = True,
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

    async def preview_insertions(
        self,
        source: str,
        file_path: str | None = None,
    ) -> dict[str, Any]:
        """Preview what type annotations would be inserted.

        Args:
            source: Python source code
            file_path: Optional file path for project-aware inference
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
        self,
        source: str,
        file_path: str | None,
        project_root: str | None = None,
    ) -> tuple[InferenceResult, dict[str, str], dict[str, dict[str, Any]]]:
        """Run inference and collect all insertable types.

        This method is primarily for benchmarks that need access to the
        inference result and raw type dictionaries.

        Args:
            source: Python source code
            file_path: Optional file path for project-aware inference
            project_root: Optional explicit project root path (e.g., from benchmark)

        Returns:
            Tuple of (inference_result, module_vars, functions)
        """
        ...

    async def collect_and_validate_types(
        self,
        source: str,
        file_path: str | None,
    ) -> tuple[InferenceResult, dict[str, TypeValidationResult]]:
        """Run inference, collect types from all scopes, and validate them.

        This method performs the orchestration logic for inlay hints:
        - Phase 1: Runs inference and collects all types from all scopes
        - Phase 2: Batch validates types with mypy (if enabled)

        Args:
            source: Python source code
            file_path: Optional file path for project-aware inference
        Returns:
            Tuple of (inference_result, validation_results)
            validation_results maps keys to TypeValidationResult objects containing
            the type string and validation status.
        """
        ...
