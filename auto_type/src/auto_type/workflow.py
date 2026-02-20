"""Type annotation workflow orchestration.

This module provides the TypeAnnotationWorkflow class that centralizes all type
annotation operations. It is used by both the LSP server and benchmarks to ensure
consistent behavior across all code paths.

All public methods are async to work with the async inference and validation engines.
"""

from typing import Any

from injector import inject

from auto_type.analysis import ScopeType
from auto_type.inference import InferenceResult  # noqa: TC001
from auto_type.inference.inference_result import FunctionInsertionInfo  # noqa: TC001
from auto_type.inference.type_recovery import (
    find_assignment_target_name_at_line,
    find_enclosing_function_for_line,
    recover_function_param_type,
    recover_function_return_type,
    recover_variable_type,
    resolve_function_scope,
)
from auto_type.insertion import (
    CodeLocation,
    InsertionTarget,
    TargetType,
    UnifiedInsertionEngine,
    build_source_index,
    create_variable_target,
    detect_assignment_pattern_indexed,
    find_assignment_target,
    find_assignment_target_indexed,
    find_function_line,
    find_variable_line,
)
from auto_type.insertion.removal_engine import TypeRemovalEngine
from auto_type.insertion.fallback_resolver import insert_variable_with_fallbacks
from auto_type.protocols.inference_engine_protocol import InferenceEngineProtocol  # noqa: TC001
from auto_type.protocols.type_validator_protocol import TypeValidatorProtocol  # noqa: TC001
from auto_type.utils.settings import Settings  # noqa: TC001
from auto_type.validation.mypy_validator import TypeValidationResult


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
        settings: Settings,
    ) -> None:
        """Initialize workflow with injected dependencies.

        Args:
            inference_engine: Engine for type inference
            insertion_engine: Engine for type insertion/removal
            type_validator: Engine for type validation
            settings: Server settings
        """
        self._inference_engine = inference_engine
        self._insertion_engine = insertion_engine
        self._type_validator = type_validator
        self._settings = settings

    def _target_type_for_annotation(self, annotation_type: str) -> TargetType:
        """Map benchmark annotation type strings to target types."""
        mapping = {
            "simple_variable": TargetType.VARIABLE_SIMPLE,
            "complex_variable": TargetType.VARIABLE_COMPLEX,
            "subscript_access": TargetType.SUBSCRIPT_ACCESS,
            "attribute_access": TargetType.ATTRIBUTE_ACCESS,
            "iteration_variable": TargetType.ITERATION_VARIABLE,
            "function_return": TargetType.FUNCTION_RETURN,
            "function_param": TargetType.FUNCTION_PARAMETER,
        }
        return mapping.get(annotation_type, TargetType.VARIABLE_SIMPLE)

    def _insert_function_return(
        self,
        source: str,
        function_name: str,
        inferred_type: str,
        inference_result: InferenceResult,
    ) -> tuple[str, bool]:
        """Insert a function return annotation."""
        func_scope = resolve_function_scope(inference_result, function_name)
        line = (
            func_scope.ast_node.lineno
            if func_scope is not None
            and hasattr(func_scope, "ast_node")
            and hasattr(func_scope.ast_node, "lineno")
            else find_function_line(source, function_name)
        )
        simple_function_name = (
            func_scope.name if func_scope is not None else function_name.split(".")[-1]
        )
        target = InsertionTarget(
            target_type=TargetType.FUNCTION_RETURN,
            location=CodeLocation(line=line, column=0),
            type_annotation=inferred_type,
            name=simple_function_name,
            metadata={"qualified_function_name": function_name},
        )
        result = self._insertion_engine.insert([target], source)
        return result.modified_source, bool(result.success and result.inserted_count > 0)

    def _insert_function_param(
        self,
        source: str,
        function_name: str,
        parameter_name: str,
        inferred_type: str,
        inference_result: InferenceResult,
    ) -> tuple[str, bool]:
        """Insert a function parameter annotation."""
        func_scope = resolve_function_scope(inference_result, function_name)
        line = (
            func_scope.ast_node.lineno
            if func_scope is not None
            and hasattr(func_scope, "ast_node")
            and hasattr(func_scope.ast_node, "lineno")
            else find_function_line(source, function_name)
        )
        target = InsertionTarget(
            target_type=TargetType.FUNCTION_PARAMETER,
            location=CodeLocation(line=line, column=0),
            type_annotation=inferred_type,
            name=parameter_name,
            metadata={
                "function_name": function_name,
                "qualified_function_name": function_name,
            },
        )
        result = self._insertion_engine.insert([target], source)
        return result.modified_source, bool(result.success and result.inserted_count > 0)

    def _create_function_targets(
        self, func_info: FunctionInsertionInfo, line: int
    ) -> list[InsertionTarget]:
        """Create InsertionTarget objects for function parameter and return annotations."""
        targets = []
        func_name = func_info["name"]

        # Add parameter annotations
        params = func_info["params"]
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
        return_type = func_info["return_type"]
        if return_type:
            target = InsertionTarget(
                target_type=TargetType.FUNCTION_RETURN,
                location=CodeLocation(line=line, column=0),
                type_annotation=return_type,
                name=func_name,
            )
            targets.append(target)

        return targets

    def _create_attribute_target(
        self, obj_name: str, attr_name: str, type_annotation: str, line: int
    ) -> InsertionTarget:
        """Create an InsertionTarget for an attribute annotation.

        Args:
            obj_name: Name of the object (e.g., 'self')
            attr_name: Name of the attribute
            type_annotation: The type annotation string
            line: Line number where the attribute is assigned

        Returns:
            InsertionTarget configured for attribute access annotation
        """
        return InsertionTarget(
            target_type=TargetType.ATTRIBUTE_ACCESS,
            location=CodeLocation(line=line, column=0),
            type_annotation=type_annotation,
            name=f"{obj_name}.{attr_name}",
            metadata={"object_name": obj_name, "attribute_name": attr_name},
        )

    async def _prepare_insertion_targets(
        self,
        source: str,
        file_path: str | None = None,
    ) -> tuple[list[InsertionTarget], int, int, str | None]:
        """Prepare insertion targets by running inference and validation.

        Shared logic for insert_all_types and preview_insertions:
        - Runs inference to get variable and function insertions
        - Validates types via type validator
        - Creates InsertionTarget objects for all valid insertions

        Args:
            source: Python source code
            file_path: Optional file path for project-aware inference
        Returns:
            Tuple of (targets, var_count, func_count, early_exit_message)
            If early_exit_message is not None, the caller should return early.
        """
        # Inference
        inference_result = self._inference_engine.infer_types(source, path=file_path)

        # Get variable, function, and attribute insertions
        variable_insertions = inference_result.get_variable_insertions()
        function_insertions = inference_result.get_function_insertions()
        attribute_insertions = inference_result.get_attribute_insertions()

        if not variable_insertions and not function_insertions and not attribute_insertions:
            return [], 0, 0, "No types to insert (no variables, functions, or attributes found)"

        # Validation
        validated_vars = await self._type_validator.validate_bulk(variable_insertions, source)

        if not validated_vars and not function_insertions and not attribute_insertions:
            return [], 0, 0, "No valid types to insert (all types failed validation)"

        # Create targets
        targets: list[InsertionTarget] = []
        source_index = build_source_index(source)

        # Variable targets
        for key, validation_result in validated_vars.items():
            if isinstance(key, tuple) and len(key) == 2:
                line_0_based, var_name = key
                var_name = str(var_name)
                resolved = (
                    find_assignment_target_indexed(source_index, var_name, line_0_based)
                    if source_index is not None
                    else find_assignment_target(source, var_name, line_0_based)
                )
            else:
                var_name = str(key)
                resolved = (
                    find_assignment_target_indexed(source_index, var_name, None)
                    if source_index is not None
                    else find_assignment_target(source, var_name, None)
                )

            if resolved is not None:
                line_1_based = resolved.line_1_based
                target_type = resolved.target_type
            else:
                line_1_based = find_variable_line(source, var_name)
                target_type = (
                    detect_assignment_pattern_indexed(source_index, var_name, line_1_based - 1)
                    if source_index is not None
                    else TargetType.VARIABLE_SIMPLE
                )
            targets.append(
                create_variable_target(
                    var_name,
                    validation_result.type_str,
                    line_1_based,
                    target_type=target_type,
                )
            )

        # Function targets
        for (line_0_based, _func_name), sig_info in function_insertions.items():
            targets.extend(self._create_function_targets(sig_info, line_0_based + 1))

        # Attribute targets
        for (line_1_based, full_attr_name), type_str in attribute_insertions.items():
            # Parse full_attr_name like "self.width" into obj_name and attr_name
            if "." in full_attr_name:
                obj_name, attr_name = full_attr_name.split(".", 1)
                targets.append(
                    self._create_attribute_target(obj_name, attr_name, type_str, line_1_based)
                )

        return targets, len(validated_vars), len(function_insertions), None

    def _collect_types_from_scopes(self, inference_result: InferenceResult) -> dict[str, str]:
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
        validation_results = await self._type_validator.validate_bulk(
            {"_single": type_annotation},
            source,
        )
        validation_result = validation_results.get(
            "_single",
            TypeValidationResult(
                type_str=type_annotation,
                is_valid=False,
                error_message="Validation failed",
            ),
        )
        if not validation_result.is_valid:
            return (
                source,
                False,
                f"Type validation failed: Type '{type_annotation}' "
                f"is not valid for variable '{variable_name}'",
            )

        # Insertion (sync - fast CPU operation)
        # Handle line number discovery
        if line_number is None:
            resolved_target = find_assignment_target(source, variable_name, None)
            line_number = (
                resolved_target.line_1_based
                if resolved_target is not None
                else find_variable_line(source, variable_name)
            )

        resolved_target = find_assignment_target(source, variable_name, line_number - 1)
        if resolved_target is not None:
            target_type = resolved_target.target_type
        else:
            target_type = TargetType.VARIABLE_SIMPLE

        # Use robust insertion with fallback targets.
        result = insert_variable_with_fallbacks(
            self._insertion_engine,
            source,
            variable_name,
            type_annotation,
            line_hint_0=(line_number - 1 if line_number > 0 else None),
            line_fallback_1=line_number,
            prefer_iteration_target=(target_type == TargetType.ITERATION_VARIABLE),
        )

        if result.success:
            return result.modified_source, True, f"Inserted {type_annotation} for {variable_name}"
        return (
            source,
            False,
            (
                f"Could not insert type for '{variable_name}': "
                f"{result.error_message or 'unknown error'}"
            ),
        )

    async def insert_all_types(
        self,
        source: str,
        file_path: str | None,
        skip_annotated: bool = True,
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
        targets, var_count, func_count, early_msg = await self._prepare_insertion_targets(
            source, file_path
        )

        if early_msg is not None:
            return source, 0, 0, early_msg

        if not targets:
            return source, 0, 0, "No types inserted (all items already annotated)"

        result = self._insertion_engine.insert(targets, source)
        if result.success:
            message = f"Inserted {result.inserted_count} type annotations"
            return result.modified_source, var_count, func_count, message
        else:
            return source, 0, 0, f"Insertion failed: {result.error_message}"

    async def preview_insertions(self, source: str, file_path: str | None = None) -> dict[str, Any]:
        """Preview what type annotations would be inserted.

        Performs inference and validation to show what changes
        would be made without actually modifying the source.

        Args:
            source: Python source code
            file_path: Optional file path for project-aware inference
        Returns:
            Dict with preview information (success, will_insert, will_skip, total_changes)
        """
        targets, _, _, early_msg = await self._prepare_insertion_targets(source, file_path)

        if early_msg is not None or not targets:
            return {
                "success": True,
                "will_insert": [],
                "will_skip": [],
                "total_changes": 0,
                "message": early_msg or "No valid types found to insert",
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
        modified_source, result_info = TypeRemovalEngine.remove_types(
            source, variables, include_functions
        )
        result_info.setdefault("skipped", result_info.get("will_skip", []))
        return modified_source, result_info

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
        return TypeRemovalEngine.preview_removals(source, variables)

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
        """Infer and insert one annotation target using production fallbacks."""
        inference_result = self._inference_engine.infer_types(
            source, path=file_path, project_root=project_root
        )
        line_0 = max(line_number - 1, 0)

        target_type = self._target_type_for_annotation(annotation_type)
        inferred_type: str | None = None
        modified_source = source
        insertion_success = False

        if target_type in {
            TargetType.VARIABLE_SIMPLE,
            TargetType.VARIABLE_COMPLEX,
            TargetType.SUBSCRIPT_ACCESS,
            TargetType.ATTRIBUTE_ACCESS,
            TargetType.ITERATION_VARIABLE,
        }:
            if variable_name is None:
                return {
                    "inferred_type": None,
                    "modified_source": source,
                    "insertion_success": False,
                    "error_message": "variable_name missing",
                }
            type_info = inference_result.scope_tree.get_variable_type_at_line(variable_name, line_0)
            if type_info and type_info.type_str != "Unknown":
                inferred_type = type_info.type_str
                line_hint_0 = type_info.line
            else:
                inferred_type = self._inference_engine.infer_expression_type(
                    source,
                    variable_name,
                    path=file_path,
                    line_hint=line_number,
                )
                if inferred_type is None:
                    inferred_type = recover_variable_type(
                        source, variable_name, line_number, inference_result
                    )
                line_hint_0 = line_0

            if inferred_type is None:
                return {
                    "inferred_type": None,
                    "modified_source": source,
                    "insertion_success": False,
                    "error_message": "Could not infer type",
                }

            insertion = insert_variable_with_fallbacks(
                self._insertion_engine,
                source,
                variable_name,
                inferred_type,
                line_hint_0=line_hint_0,
                line_fallback_1=line_number if line_number > 0 else None,
                prefer_iteration_target=(target_type == TargetType.ITERATION_VARIABLE),
            )
            modified_source = insertion.modified_source
            insertion_success = bool(insertion.success and insertion.inserted_count > 0)

        elif target_type == TargetType.FUNCTION_RETURN:
            if function_name is None:
                return {
                    "inferred_type": None,
                    "modified_source": source,
                    "insertion_success": False,
                    "error_message": "function_name missing",
                }
            func_scope = resolve_function_scope(inference_result, function_name)
            if (
                func_scope
                and func_scope.return_type
                and func_scope.return_type.type_str != "Unknown"
            ):
                inferred_type = func_scope.return_type.type_str
            if inferred_type is None:
                inferred_type = recover_function_return_type(source, function_name)
            if inferred_type is None:
                return {
                    "inferred_type": None,
                    "modified_source": source,
                    "insertion_success": False,
                    "error_message": "Could not infer function return type",
                }
            modified_source, insertion_success = self._insert_function_return(
                source, function_name, inferred_type, inference_result
            )

        elif target_type == TargetType.FUNCTION_PARAMETER:
            if function_name is None or parameter_name is None:
                return {
                    "inferred_type": None,
                    "modified_source": source,
                    "insertion_success": False,
                    "error_message": "function_name or parameter_name missing",
                }
            if function_name == "lambda":
                inferred_type = recover_function_param_type(
                    source, function_name, parameter_name, line_number
                )
                if inferred_type is None:
                    return {
                        "inferred_type": None,
                        "modified_source": source,
                        "insertion_success": False,
                        "error_message": "Could not infer lambda parameter type",
                    }
                assignment_target = find_assignment_target_name_at_line(source, line_number)
                lambda_target = (
                    assignment_target if assignment_target is not None else parameter_name
                )
                insertion = insert_variable_with_fallbacks(
                    self._insertion_engine,
                    source,
                    lambda_target,
                    inferred_type,
                    line_hint_0=(line_number - 1 if line_number > 0 else None),
                    line_fallback_1=line_number if line_number > 0 else None,
                )
                modified_source = insertion.modified_source
                insertion_success = bool(insertion.success and insertion.inserted_count > 0)
                if not insertion_success:
                    enclosing = find_enclosing_function_for_line(source, line_number)
                    if enclosing is not None:
                        modified_source, insertion_success = self._insert_function_return(
                            source, enclosing.name, inferred_type, inference_result
                        )
            else:
                func_scope = resolve_function_scope(inference_result, function_name)
                if func_scope and parameter_name in func_scope.parameters:
                    param_type = func_scope.parameters[parameter_name]
                    if param_type.type_str != "Unknown":
                        inferred_type = param_type.type_str
                if inferred_type is None:
                    inferred_type = recover_function_param_type(
                        source, function_name, parameter_name, line_number
                    )
                if inferred_type is None:
                    return {
                        "inferred_type": None,
                        "modified_source": source,
                        "insertion_success": False,
                        "error_message": "Could not infer function parameter type",
                    }
                modified_source, insertion_success = self._insert_function_param(
                    source,
                    function_name,
                    parameter_name,
                    inferred_type,
                    inference_result,
                )
        else:
            return {
                "inferred_type": None,
                "modified_source": source,
                "insertion_success": False,
                "error_message": f"Unsupported annotation type: {annotation_type}",
            }

        return {
            "inferred_type": inferred_type,
            "modified_source": modified_source,
            "insertion_success": insertion_success,
            "error_message": None if insertion_success else "Insertion failed",
        }

    async def infer_and_collect_types(
        self,
        source: str,
        file_path: str | None,
        project_root: str | None = None,
    ) -> tuple[InferenceResult, dict[str, str], dict[str, FunctionInsertionInfo]]:
        """Run inference and collect all insertable types.

        This method is primarily for benchmarks that need access to the
        inference result and raw type dictionaries for individual type testing.

        Args:
            source: Python source code
            file_path: Optional file path for project-aware inference
            project_root: Optional explicit project root path (e.g., from benchmark)

        Returns:
            Tuple of:
                - InferenceResult: The complete inference result with scope tree
                - module_vars: Dict mapping variable names to type strings
                - functions: Dict mapping function IDs to their annotation info
        """
        inference_result = self._inference_engine.infer_types(
            source, path=file_path, project_root=project_root
        )
        all_insertable = inference_result.get_all_insertable_types()
        return (
            inference_result,
            all_insertable["module_vars"],
            all_insertable["functions"],
        )

    async def collect_and_validate_types(
        self, source: str, file_path: str | None
    ) -> tuple[InferenceResult, dict[str, TypeValidationResult]]:
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
                - validation_results: Dict mapping unique keys to TypeValidationResult
                  Keys are formatted as: "{scope_id}.{category}.{name}"
                  e.g., "module.var.x", "func_foo.param.arg1", "func_foo.return"
                  Each result includes the type string and validation status.
        """
        # Run inference (sync)
        inference_result = self._inference_engine.infer_types(source, path=file_path)

        # Phase 1: Collect all types from all scopes (sync - fast CPU operation)
        all_types = self._collect_types_from_scopes(inference_result)

        # Phase 2: Validate - async (only if enabled)
        if self._settings.mypy_inference_validation_enabled:
            validated_types = await self._type_validator.validate_bulk(all_types, source)
        else:
            # Create optimistic results if validation is disabled
            validated_types = {
                key: TypeValidationResult(type_str=type_str, is_valid=True)
                for key, type_str in all_types.items()
            }

        return inference_result, validated_types
