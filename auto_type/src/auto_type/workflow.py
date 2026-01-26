"""Type annotation workflow orchestration.

This module provides the TypeAnnotationWorkflow class that centralizes all type
annotation operations. It is used by both the LSP server and benchmarks to ensure
consistent behavior across all code paths.

All public methods are async to work with the async inference and validation engines.
"""

from typing import TYPE_CHECKING, Any

from injector import inject

from auto_type.analysis.types import ScopeType
from auto_type.insertion import (
    CodeLocation,
    InsertionTarget,
    TargetType,
    UnifiedInsertionEngine,
)
from auto_type.protocols.inference_engine_protocol import InferenceEngineProtocol
from auto_type.protocols.type_validator_protocol import TypeValidatorProtocol

if TYPE_CHECKING:
    from auto_type.inference.inference_result import InferenceResult


class TypeAnnotationWorkflow:
    """Orchestrates type inference, validation, and insertion workflows.

    This class centralizes all type annotation operations and is used by both
    the LSP server and benchmarks. It handles:
    - Type inference via JediInferenceEngine
    - Type validation via MypyTypeValidator
    - Type insertion/removal via InsertionEngine

    Dependencies are injected via constructor for testability and consistency.
    All public methods are async to work with async engines.
    """

    @inject
    def __init__(
        self,
        inference_engine: InferenceEngineProtocol,
        insertion_engine: UnifiedInsertionEngine,
        type_validator: TypeValidatorProtocol,
    ) -> None:
        """Initialize workflow with injected dependencies.

        Args:
            inference_engine: Engine for type inference
            insertion_engine: Engine for type insertion/removal
            type_validator: Engine for type validation
        """
        self._inference_engine = inference_engine
        self._insertion_engine = insertion_engine
        self._type_validator = type_validator

    # Helper methods for creating InsertionTarget objects

    def _create_variable_target(
        self, name: str, type_annotation: str, line: int
    ) -> InsertionTarget:
        """Create an InsertionTarget for a variable annotation."""
        return InsertionTarget(
            target_type=TargetType.VARIABLE_SIMPLE,
            location=CodeLocation(line=line, column=0),
            type_annotation=type_annotation,
            name=name,
        )

    def _create_function_targets(
        self, func_info: dict[str, Any], line: int
    ) -> list[InsertionTarget]:
        """Create InsertionTarget objects for function parameter and return annotations."""
        targets = []
        func_name = func_info["name"]

        # Add parameter annotations
        params = func_info.get("parameters", {})
        for param_name, param_type in params.items():
            target = InsertionTarget(
                target_type=TargetType.FUNCTION_PARAMETER,
                location=CodeLocation(line=line, column=0),
                type_annotation=param_type,
                name=param_name,
                metadata={"function_name": func_name},
            )
            targets.append(target)

        # Add return type annotation
        return_type = func_info.get("return_type")
        if return_type:
            target = InsertionTarget(
                target_type=TargetType.FUNCTION_RETURN,
                location=CodeLocation(line=line, column=0),
                type_annotation=return_type,
                name=func_name,
            )
            targets.append(target)

        return targets

    def _find_variable_line(self, source: str, variable_name: str) -> int:
        """Find the line number where a variable is assigned.

        This is a simple fallback implementation. In practice, proper AST
        analysis would be used for accurate line finding.
        """
        lines = source.split("\n")
        for i, line in enumerate(lines, 1):
            if f"{variable_name} =" in line and not line.strip().startswith("#"):
                return i
        return 1  # Fallback to line 1

    def _find_function_line(self, source: str, function_name: str) -> int:
        """Find the line number where a function is defined."""
        lines = source.split("\n")
        for i, line in enumerate(lines, 1):
            if f"def {function_name}(" in line:
                return i
        return 1  # Fallback to line 1

    async def insert_single_type(
        self,
        source: str,
        variable_name: str,
        type_annotation: str,
        line_number: int | None = None,
    ) -> tuple[str, bool, str]:
        """Insert type annotation for a single variable.

        Validates the type using mypy, then inserts the annotation.

        Args:
            source: Python source code
            variable_name: Name of the variable to annotate
            type_annotation: The type string to insert
            line_number: Optional 1-based line number to target a specific assignment

        Returns:
            Tuple of (modified_source, success, message)
        """
        # Validation
        is_valid, error_msg = await self._type_validator.validate_insertion(
            source, variable_name, type_annotation
        )
        if not is_valid:
            return source, False, f"Type validation failed: {error_msg}"

        # Insertion (sync - fast CPU operation)
        # Handle line number discovery
        if line_number is None:
            line_number = self._find_variable_line(source, variable_name)

        # Create target for unified engine
        target = self._create_variable_target(variable_name, type_annotation, line_number)

        # Use unified engine
        result = self._insertion_engine.insert([target], source)

        if result.success:
            return result.modified_source, True, f"Inserted {type_annotation} for {variable_name}"
        return (
            source,
            False,
            (
                f"Could not insert type for '{variable_name}': {result.error_message or 'unknown error'}"
            ),
        )

    async def insert_all_types(
        self, source: str, file_path: str | None, skip_annotated: bool = True
    ) -> tuple[str, int, int, str]:
        """Insert all inferred types in a file.

        Performs inference, validation, and bulk insertion of both
        module-level variables and function signatures.

        Args:
            source: Python source code
            file_path: Optional file path for project-aware inference
            skip_annotated: If True, skip items that already have annotations

        Returns:
            Tuple of (modified_source, var_count, func_count, message)
        """
        # Inference (async)
        inference_result = await self._inference_engine.infer_types(source, path=file_path)

        # Get variable insertions for all scopes (keyed by (line, var_name))
        variable_insertions = inference_result.get_variable_insertions()

        # Get function signatures (keyed by (line, func_name))
        function_insertions = inference_result.get_function_insertions()

        if not variable_insertions and not function_insertions:
            return source, 0, 0, "No types to insert (no variables or functions found)"

        # Validation - async
        validated_vars = await self._type_validator.validate_bulk(variable_insertions, source)

        if not validated_vars and not function_insertions:
            return source, 0, 0, "No valid types to insert (all types failed validation)"

        # Insertion (sync - fast CPU operations)
        targets = []

        # Create targets for validated variables
        if validated_vars:
            for var_name, type_str in validated_vars.items():
                line = self._find_variable_line(source, var_name)
                targets.append(self._create_variable_target(var_name, type_str, line))

        # Create targets for function insertions
        if function_insertions:
            for (line, func_name), sig_info in function_insertions.items():
                # Convert function_insertions format to what _create_function_targets expects
                func_info = {**sig_info, "name": func_name}
                targets.extend(self._create_function_targets(func_info, line))

        # Single unified insertion for all targets
        if targets:
            result = self._insertion_engine.insert(targets, source)
            if result.success:
                total = result.inserted_count
                # For now, we can't easily distinguish between var and func counts
                # from the unified result, so we'll use total for both display purposes
                message = f"Inserted {total} type annotations"
                var_count = len(validated_vars) if result.success else 0
                func_count = len(function_insertions) if result.success else 0
                return result.modified_source, var_count, func_count, message
            else:
                return source, 0, 0, f"Insertion failed: {result.error_message}"

        return source, 0, 0, "No types inserted (all items already annotated)"

    async def preview_insertions(self, source: str) -> dict[str, Any]:
        """Preview what type annotations would be inserted.

        Performs inference and validation to show what changes
        would be made without actually modifying the source.

        Args:
            source: Python source code

        Returns:
            Dict with preview information (success, will_insert, will_skip, total_changes)
        """
        # Get all inferred types (async)
        inference_result = await self._inference_engine.infer_types(source)
        variable_insertions = inference_result.get_variable_insertions()

        if not variable_insertions:
            return {
                "success": True,
                "will_insert": [],
                "will_skip": [],
                "total_changes": 0,
                "message": "No types found to insert",
            }

        # Validation - async
        validated_types = await self._type_validator.validate_bulk(variable_insertions, source)

        # Create targets for preview
        targets = []
        for var_name, type_str in validated_types.items():
            line = self._find_variable_line(source, var_name)
            targets.append(self._create_variable_target(var_name, type_str, line))

        # Get preview from insertion engine (sync - fast)
        if not targets:
            return {
                "success": True,
                "will_insert": [],
                "will_skip": [],
                "total_changes": 0,
                "message": "No valid types found to insert",
            }

        return self._insertion_engine.preview_insertions(targets, source)

    def remove_types(
        self, source: str, variables: list[str] | None = None, include_functions: bool = False
    ) -> tuple[str, dict[str, Any]]:
        """Remove type annotations from source.

        This method is sync because it only uses the insertion engine
        which performs fast CPU-bound operations.

        Note: Type removal is not yet implemented in UnifiedInsertionEngine.

        Args:
            source: Python source code
            variables: Optional list of variable names to remove annotations from.
                       If None, removes all annotations.
            include_functions: If True, also remove function annotations

        Returns:
            Tuple of (modified_source, result_info)
            result_info contains: success, removed_count, not_found, skipped
        """
        result_info = {
            "success": False,
            "removed_count": 0,
            "details": {},
            "error_message": "Type removal not yet implemented in UnifiedInsertionEngine",
        }
        return source, result_info

    def preview_removals(self, source: str, variables: list[str] | None = None) -> dict[str, Any]:
        """Preview what type annotations would be removed.

        This method is sync because it only uses the insertion engine
        which performs fast CPU-bound operations.

        Note: Type removal preview is not yet implemented in UnifiedInsertionEngine.

        Args:
            source: Python source code
            variables: Optional list of variable names to preview.
                       If None, previews all annotations.

        Returns:
            Dict with preview information (success, will_remove, not_found,
            will_skip, total_changes)
        """
        return {
            "success": False,
            "error_message": "Type removal preview not yet implemented in UnifiedInsertionEngine",
        }

    async def infer_and_collect_types(
        self, source: str, file_path: str | None
    ) -> tuple["InferenceResult", dict[str, str], dict[str, dict[str, Any]]]:
        """Run inference and collect all insertable types.

        This method is primarily for benchmarks that need access to the
        inference result and raw type dictionaries for individual type testing.

        Args:
            source: Python source code
            file_path: Optional file path for project-aware inference

        Returns:
            Tuple of:
                - InferenceResult: The complete inference result with scope tree
                - module_vars: Dict mapping variable names to type strings
                - functions: Dict mapping function IDs to their annotation info
        """
        inference_result = await self._inference_engine.infer_types(source, path=file_path)
        all_insertable = inference_result.get_all_insertable_types()
        return (
            inference_result,
            all_insertable["module_vars"],
            all_insertable["functions"],
        )

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
            Tuple of:
                - InferenceResult: The complete inference result with scope tree
                - validated_types: Dict mapping unique keys to validated type strings
                  Keys are formatted as: "{scope_id}.{category}.{name}"
                  e.g., "module.var.x", "func_foo.param.arg1", "func_foo.return"
        """
        # Run inference (async)
        inference_result = await self._inference_engine.infer_types(source, path=file_path)

        # Phase 1: Collect all types from all scopes (sync - fast CPU operation)
        all_types = self._collect_types_from_scopes(inference_result)

        # Phase 2: Validate - async
        validated_types = await self._type_validator.validate_bulk(all_types, source)

        return inference_result, validated_types

    def _collect_types_from_scopes(self, inference_result: "InferenceResult") -> dict[str, str]:
        """Collect all types from all scopes in the inference result.

        This is a helper method extracted for reuse. It's sync because it only
        iterates over in-memory data structures.

        Args:
            inference_result: The inference result containing the scope tree

        Returns:
            Dict mapping unique keys to type strings
        """
        all_types: dict[str, str] = {}
        for scope_id, scope_obj in inference_result.scope_tree.scopes_by_id.items():
            # Collect local variables
            for var_name, type_info in scope_obj.variables.items():
                if type_info.type_str != "Unknown":
                    key = f"{scope_id}.var.{var_name}"
                    all_types[key] = type_info.type_str

            # Collect function parameters and return types
            if scope_obj.scope_type == ScopeType.FUNCTION:
                for param_name, type_info in scope_obj.parameters.items():
                    if type_info.type_str != "Unknown":
                        key = f"{scope_id}.param.{param_name}"
                        all_types[key] = type_info.type_str

                if scope_obj.return_type and scope_obj.return_type.type_str != "Unknown":
                    key = f"{scope_id}.return"
                    all_types[key] = scope_obj.return_type.type_str

        return all_types
