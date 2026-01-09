"""Core type annotation insertion and removal engine using LibCST.

This module provides the InsertionEngine class which handles:
1. Parsing Python source code with LibCST
2. Finding variable assignments without type annotations
3. Inserting type annotations while preserving formatting
4. Removing type annotations while preserving formatting
5. Handling both single variable and bulk file operations
"""

import logging
from typing import Any

import libcst as cst

logger = logging.getLogger(__name__)


class TypeAnnotationTransformer(cst.CSTTransformer):
    """LibCST transformer that adds type annotations to variables.

    This transformer visits AnnAssign and Assign nodes and adds type
    annotations where specified in the types_to_insert mapping.
    """

    def __init__(self, types_to_insert: dict[str, str]) -> None:
        """Initialize the transformer.

        Args:
            types_to_insert: Mapping of variable names to type strings
                           e.g., {"x": "int", "name": "str"}
        """
        super().__init__()
        self.types_to_insert = types_to_insert
        self.inserted_count = 0

    def leave_Assign(
        self, original_node: cst.Assign, updated_node: cst.Assign
    ) -> cst.Assign | cst.AnnAssign:
        """Transform simple assignments to annotated assignments.

        Converts:
            x = 42
        To:
            x: int = 42

        Only transforms if:
        1. The assignment target is a simple Name (not tuple/list unpacking)
        2. The variable name is in types_to_insert
        3. There's a value being assigned (not just a bare assignment)

        Args:
            original_node: The original Assign node
            updated_node: The updated Assign node (from previous transforms)

        Returns:
            Either the original Assign or a new AnnAssign with type annotation
        """
        # Only handle simple assignments like "x = 42"
        # Skip tuple unpacking like "x, y = 1, 2"
        if len(updated_node.targets) != 1:
            return updated_node

        target = updated_node.targets[0].target

        # Only handle direct name assignments (not attributes or subscripts)
        if not isinstance(target, cst.Name):
            return updated_node

        var_name = target.value

        # Check if we should add a type annotation for this variable
        if var_name not in self.types_to_insert:
            return updated_node

        type_str = self.types_to_insert[var_name]
        logger.debug(f"Inserting type annotation for {var_name}: {type_str}")

        # Parse the type string into a LibCST annotation
        try:
            type_annotation = cst.parse_expression(type_str)
        except Exception as e:
            logger.error(f"Failed to parse type annotation '{type_str}': {e}")
            return updated_node

        # Create an annotated assignment: x: int = 42
        ann_assign = cst.AnnAssign(
            target=target,
            annotation=cst.Annotation(annotation=type_annotation),
            value=updated_node.value,
            semicolon=updated_node.semicolon,
        )

        self.inserted_count += 1
        return ann_assign

    def leave_AnnAssign(
        self, original_node: cst.AnnAssign, updated_node: cst.AnnAssign
    ) -> cst.AnnAssign:
        """Leave existing annotated assignments unchanged.

        If a variable already has a type annotation, we respect the user's
        choice and don't modify it. This is a key design principle.

        Args:
            original_node: The original AnnAssign node
            updated_node: The updated AnnAssign node

        Returns:
            The unchanged AnnAssign node
        """
        # If variable already has annotation, skip it
        if isinstance(updated_node.target, cst.Name):
            var_name = updated_node.target.value
            if var_name in self.types_to_insert:
                logger.debug(
                    f"Skipping {var_name} - already has annotation: "
                    f"{updated_node.annotation.annotation}"
                )
                # Remove from types_to_insert to track what we skipped
                # (Don't actually remove - we might want to report this)
        return updated_node


class TypeReplacementTransformer(cst.CSTTransformer):
    """LibCST transformer that replaces type annotations for variables.

    This transformer visits AnnAssign nodes and replaces their type
    annotations with new ones.
    """

    def __init__(self, types_to_replace: dict[str, str]) -> None:
        """Initialize the transformer.

        Args:
            types_to_replace: Mapping of variable names to new type strings
                             e.g., {"x": "int"} will replace x's annotation with int
        """
        super().__init__()
        self.types_to_replace = types_to_replace
        self.replaced_count = 0

    def leave_AnnAssign(
        self, original_node: cst.AnnAssign, updated_node: cst.AnnAssign
    ) -> cst.AnnAssign:
        """Replace type annotations for specified variables.

        Converts:
            x: str = 42  →  x: int = 42

        Only transforms if:
        1. The assignment target is a simple Name (not attributes/subscripts)
        2. The variable name is in types_to_replace

        Args:
            original_node: The original AnnAssign node
            updated_node: The updated AnnAssign node (from previous transforms)

        Returns:
            AnnAssign with replaced type annotation, or unchanged if not in types_to_replace
        """
        # Only handle simple name targets
        if not isinstance(updated_node.target, cst.Name):
            return updated_node

        var_name = updated_node.target.value

        # Check if we should replace this annotation
        if var_name not in self.types_to_replace:
            return updated_node

        new_type_str = self.types_to_replace[var_name]
        logger.debug(f"Replacing type annotation for {var_name} with {new_type_str}")

        # Parse the new type string into a LibCST annotation
        try:
            new_type_annotation = cst.parse_expression(new_type_str)
        except Exception as e:
            logger.error(f"Failed to parse type annotation '{new_type_str}': {e}")
            return updated_node

        # Create new annotated assignment with replaced type
        new_ann_assign = updated_node.with_changes(
            annotation=cst.Annotation(annotation=new_type_annotation)
        )

        self.replaced_count += 1
        return new_ann_assign


class TypeRemovalTransformer(cst.CSTTransformer):
    """LibCST transformer that removes type annotations from variables.

    This transformer visits AnnAssign nodes and converts them back to
    regular Assign nodes, effectively removing the type annotations.
    """

    def __init__(self, variables_to_remove: set[str] | None = None) -> None:
        """Initialize the transformer.

        Args:
            variables_to_remove: Set of variable names to remove annotations from.
                                If None, remove ALL type annotations.
        """
        super().__init__()
        self.variables_to_remove = variables_to_remove  # None means "remove all"
        self.removed_count = 0

    def leave_AnnAssign(
        self, original_node: cst.AnnAssign, updated_node: cst.AnnAssign
    ) -> cst.AnnAssign | cst.Assign:
        """Transform annotated assignments to regular assignments.

        Converts:
            x: int = 42  →  x = 42
        Skips:
            x: int       (no value, leave as-is per design decision)

        Only transforms if:
        1. The assignment target is a simple Name (not attributes/subscripts)
        2. The variable name is in variables_to_remove (or variables_to_remove is None)
        3. There's a value being assigned (skip variable declarations without values)

        Args:
            original_node: The original AnnAssign node
            updated_node: The updated AnnAssign node (from previous transforms)

        Returns:
            Either a new Assign (annotation removed) or unchanged AnnAssign
        """
        # Only handle simple name targets (not self.x, obj[key], etc.)
        if not isinstance(updated_node.target, cst.Name):
            return updated_node

        var_name = updated_node.target.value

        # Check if we should remove this annotation
        if self.variables_to_remove is not None and var_name not in self.variables_to_remove:
            return updated_node  # Keep this annotation

        # Skip if no value (e.g., "x: int" with no assignment)
        # This is a variable declaration, not an assignment
        if updated_node.value is None:
            logger.debug(f"Skipping {var_name} - no value (declaration only)")
            return updated_node

        logger.debug(f"Removing type annotation from {var_name}")

        # Convert AnnAssign to Assign: "x: int = 42" → "x = 42"
        assign = cst.Assign(
            targets=[cst.AssignTarget(target=updated_node.target)],
            value=updated_node.value,
            semicolon=updated_node.semicolon,
        )

        self.removed_count += 1
        return assign


class FunctionSignatureTransformer(cst.CSTTransformer):
    """LibCST transformer that adds type annotations to function signatures.

    This transformer visits FunctionDef nodes and adds parameter type
    annotations and return type annotations where specified.
    """

    def __init__(self, function_annotations: dict[str, dict[str, Any]]) -> None:
        """Initialize the transformer.

        Args:
            function_annotations: Dict mapping function names to their annotations.
                Format: {
                    "func_name": {
                        "params": {"param1": "int", "param2": "str"},
                        "return": "bool"
                    }
                }
        """
        self.function_annotations = function_annotations
        self.modified_count = 0
        self.logger = logging.getLogger(__name__)

    def leave_FunctionDef(
        self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef
    ) -> cst.FunctionDef:
        """Add type annotations to function signature.

        Args:
            original_node: Original function definition node
            updated_node: Updated function definition node

        Returns:
            Modified function definition with type annotations
        """
        func_name = original_node.name.value

        # Check if we have annotations for this function
        if func_name not in self.function_annotations:
            return updated_node

        annotations = self.function_annotations[func_name]
        params_to_annotate = annotations.get("params", {})
        return_type = annotations.get("return")

        modified = False

        # Add parameter annotations
        if params_to_annotate:
            new_params = []
            for param in updated_node.params.params:
                param_name = param.name.value

                # Skip if already annotated or not in our list
                if param.annotation is not None or param_name not in params_to_annotate:
                    new_params.append(param)
                    continue

                # Add type annotation
                type_str = params_to_annotate[param_name]
                try:
                    type_annotation = cst.parse_expression(type_str)
                    new_param = param.with_changes(
                        annotation=cst.Annotation(annotation=type_annotation)
                    )
                    new_params.append(new_param)
                    modified = True
                except Exception as e:
                    self.logger.warning(
                        f"Failed to parse type '{type_str}' for param {param_name}: {e}"
                    )
                    new_params.append(param)

            if modified:
                updated_node = updated_node.with_changes(
                    params=updated_node.params.with_changes(params=new_params)
                )

        # Add return type annotation
        if return_type and updated_node.returns is None:
            try:
                return_annotation = cst.parse_expression(return_type)
                updated_node = updated_node.with_changes(
                    returns=cst.Annotation(annotation=return_annotation)
                )
                modified = True
            except Exception as e:
                self.logger.warning(
                    f"Failed to parse return type '{return_type}' for {func_name}: {e}"
                )

        if modified:
            self.modified_count += 1

        return updated_node

    leave_AsyncFunctionDef = leave_FunctionDef  # Handle async functions the same way


class InsertionEngine:
    """Engine for inserting and removing type annotations in Python source code.

    This class provides high-level methods to:
    1. Insert a type annotation for a single variable
    2. Insert type annotations for all variables in a file
    3. Remove a type annotation from a single variable
    4. Remove type annotations from variables in a file
    5. Preview what changes would be made (insertions or removals)

    The engine uses LibCST to preserve code formatting and comments.
    """

    def __init__(self) -> None:
        """Initialize the insertion engine."""
        self.logger = logging.getLogger(__name__)

    def insert_type(
        self, source: str, variable_name: str, type_annotation: str
    ) -> tuple[str, bool]:
        """Insert a type annotation for a single variable.

        Args:
            source: The Python source code
            variable_name: Name of the variable to annotate
            type_annotation: The type string (e.g., "int", "list[str]")

        Returns:
            Tuple of (modified_source, success)
            - modified_source: The source with type annotation inserted
            - success: True if insertion was successful, False otherwise

        Example:
            >>> engine = InsertionEngine()
            >>> source = "x = 42\\n"
            >>> modified, success = engine.insert_type(source, "x", "int")
            >>> print(modified)
            x: int = 42
        """
        self.logger.info(f"Inserting type '{type_annotation}' for variable '{variable_name}'")

        try:
            # Parse source code into CST
            tree = cst.parse_module(source)

            # Create transformer with single variable to insert
            transformer = TypeAnnotationTransformer({variable_name: type_annotation})

            # Transform the tree
            modified_tree = tree.visit(transformer)

            # Convert back to source code
            modified_source = modified_tree.code

            if transformer.inserted_count > 0:
                self.logger.info(f"Successfully inserted type annotation for '{variable_name}'")
                return modified_source, True
            else:
                self.logger.warning(
                    f"No insertion made for '{variable_name}' - "
                    "variable not found or already annotated"
                )
                return source, False

        except Exception as e:
            self.logger.error(f"Error inserting type annotation: {e}", exc_info=True)
            return source, False

    def insert_types_bulk(
        self, source: str, types_map: dict[str, str], skip_annotated: bool = True
    ) -> tuple[str, dict[str, Any]]:
        """Insert type annotations for multiple variables in one pass.

        Args:
            source: The Python source code
            types_map: Mapping of variable names to type strings
                      e.g., {"x": "int", "name": "str", "items": "list[str]"}
            skip_annotated: If True, skip variables that already have annotations
                           (default: True, respects user's explicit choices)

        Returns:
            Tuple of (modified_source, result_info)
            - modified_source: The source with all type annotations inserted
            - result_info: Dict with keys:
                - "success": bool
                - "inserted_count": int (number of annotations inserted)
                - "skipped": list[str] (variables skipped)
                - "failed": list[str] (variables that failed)

        Example:
            >>> engine = InsertionEngine()
            >>> source = "x = 42\\nname = 'hello'\\n"
            >>> types = {"x": "int", "name": "str"}
            >>> modified, info = engine.insert_types_bulk(source, types)
            >>> print(info["inserted_count"])
            2
        """
        self.logger.info(f"Inserting {len(types_map)} type annotations in bulk")

        try:
            # Parse source code into CST
            tree = cst.parse_module(source)

            # If skip_annotated, we need to filter out already-annotated variables
            if skip_annotated:
                types_to_insert = self._filter_annotated_variables(tree, types_map)
                skipped = [v for v in types_map if v not in types_to_insert]
            else:
                types_to_insert = types_map
                skipped = []

            # Create transformer
            transformer = TypeAnnotationTransformer(types_to_insert)

            # Transform the tree
            modified_tree = tree.visit(transformer)

            # Convert back to source code
            modified_source = modified_tree.code

            # Calculate what failed (in types_to_insert but not inserted)
            expected_insertions = len(types_to_insert)
            actual_insertions = transformer.inserted_count
            failed_count = expected_insertions - actual_insertions

            result_info = {
                "success": actual_insertions > 0,
                "inserted_count": actual_insertions,
                "skipped": skipped,
                "failed": [],  # We don't track individual failures yet
                "total_requested": len(types_map),
            }

            self.logger.info(
                f"Bulk insertion complete: {actual_insertions} inserted, "
                f"{len(skipped)} skipped, {failed_count} not found"
            )

            return modified_source, result_info

        except Exception as e:
            self.logger.error(f"Error in bulk type insertion: {e}", exc_info=True)
            return source, {
                "success": False,
                "inserted_count": 0,
                "skipped": [],
                "failed": list(types_map.keys()),
                "total_requested": len(types_map),
                "error": str(e),
            }

    def _filter_annotated_variables(
        self, tree: cst.Module, types_map: dict[str, str]
    ) -> dict[str, str]:
        """Filter out variables that already have type annotations.

        Args:
            tree: The parsed LibCST module
            types_map: The original mapping of variables to types

        Returns:
            Filtered mapping excluding already-annotated variables
        """
        # Find all variables that already have annotations
        annotated_vars: set[str] = set()

        class AnnotationFinder(cst.CSTVisitor):
            def visit_AnnAssign(self, node: cst.AnnAssign) -> None:
                if isinstance(node.target, cst.Name):
                    annotated_vars.add(node.target.value)

        # Use the visitor to walk the tree
        visitor = AnnotationFinder()
        tree.visit(visitor)

        # Filter out annotated variables
        filtered = {
            var: type_str for var, type_str in types_map.items() if var not in annotated_vars
        }

        if len(filtered) < len(types_map):
            skipped = set(types_map.keys()) - set(filtered.keys())
            self.logger.debug(f"Filtering out already-annotated variables: {skipped}")

        return filtered

    def preview_insertions(self, source: str, types_map: dict[str, str]) -> dict[str, Any]:
        """Preview what type annotations would be inserted without modifying source.

        Args:
            source: The Python source code
            types_map: Mapping of variable names to type strings

        Returns:
            Dict with preview information:
            - "will_insert": list[dict] with {"variable": str, "type": str}
            - "will_skip": list[dict] with {"variable": str, "reason": str}
            - "total_changes": int

        Example:
            >>> engine = InsertionEngine()
            >>> source = "x = 42\\ny: str = 'hello'\\n"
            >>> types = {"x": "int", "y": "str"}
            >>> preview = engine.preview_insertions(source, types)
            >>> print(preview["total_changes"])
            1
        """
        self.logger.info(f"Generating preview for {len(types_map)} type annotations")

        try:
            # Parse source
            tree = cst.parse_module(source)

            # Find annotated variables
            annotated_vars: set[str] = set()

            class AnnotationFinder(cst.CSTVisitor):
                def visit_AnnAssign(self, node: cst.AnnAssign) -> None:
                    if isinstance(node.target, cst.Name):
                        annotated_vars.add(node.target.value)

            # Use the visitor to walk the tree
            visitor = AnnotationFinder()
            tree.visit(visitor)

            # Build preview
            will_insert = []
            will_skip = []

            for var_name, type_str in types_map.items():
                if var_name in annotated_vars:
                    will_skip.append(
                        {
                            "variable": var_name,
                            "type": type_str,
                            "reason": "Already has type annotation",
                        }
                    )
                else:
                    will_insert.append({"variable": var_name, "type": type_str})

            return {
                "will_insert": will_insert,
                "will_skip": will_skip,
                "total_changes": len(will_insert),
                "success": True,
            }

        except Exception as e:
            self.logger.error(f"Error generating preview: {e}", exc_info=True)
            return {
                "will_insert": [],
                "will_skip": [],
                "total_changes": 0,
                "success": False,
                "error": str(e),
            }

    def replace_type(self, source: str, variable_name: str, new_type: str) -> tuple[str, bool]:
        """Replace the type annotation for a variable.

        Args:
            source: The Python source code
            variable_name: Name of the variable to replace annotation for
            new_type: The new type string (e.g., "int", "list[str]")

        Returns:
            Tuple of (modified_source, success)
            - modified_source: The source with type annotation replaced
            - success: True if replacement was successful, False otherwise

        Example:
            >>> engine = InsertionEngine()
            >>> source = "x: str = 42\\n"
            >>> modified, success = engine.replace_type(source, "x", "int")
            >>> print(modified)
            x: int = 42
        """
        self.logger.info(f"Replacing type annotation for '{variable_name}' with '{new_type}'")

        try:
            # Parse source code into CST
            tree = cst.parse_module(source)

            # Create transformer with single variable to replace
            transformer = TypeReplacementTransformer({variable_name: new_type})

            # Transform the tree
            modified_tree = tree.visit(transformer)

            # Convert back to source code
            modified_source = modified_tree.code

            if transformer.replaced_count > 0:
                self.logger.info(f"Successfully replaced type annotation for '{variable_name}'")
                return modified_source, True
            else:
                self.logger.warning(
                    f"No replacement made for '{variable_name}' - "
                    "variable not found or not annotated"
                )
                return source, False

        except Exception as e:
            self.logger.error(f"Error replacing type annotation: {e}", exc_info=True)
            return source, False

    def remove_type(self, source: str, variable_name: str) -> tuple[str, bool]:
        """Remove type annotation from a single variable.

        Args:
            source: The Python source code
            variable_name: Name of the variable to remove annotation from

        Returns:
            Tuple of (modified_source, success)
            - modified_source: The source with type annotation removed
            - success: True if removal was successful, False otherwise

        Example:
            >>> engine = InsertionEngine()
            >>> source = "x: int = 42\\n"
            >>> modified, success = engine.remove_type(source, "x")
            >>> print(modified)
            x = 42
        """
        self.logger.info(f"Removing type annotation for variable '{variable_name}'")

        try:
            # Parse source code into CST
            tree = cst.parse_module(source)

            # Create transformer with single variable to remove
            transformer = TypeRemovalTransformer({variable_name})

            # Transform the tree
            modified_tree = tree.visit(transformer)

            # Convert back to source code
            modified_source = modified_tree.code

            if transformer.removed_count > 0:
                self.logger.info(f"Successfully removed type annotation for '{variable_name}'")
                return modified_source, True
            else:
                self.logger.warning(
                    f"No removal made for '{variable_name}' - variable not found or not annotated"
                )
                return source, False

        except Exception as e:
            self.logger.error(f"Error removing type annotation: {e}", exc_info=True)
            return source, False

    def remove_types_bulk(
        self, source: str, variables: list[str] | None = None, include_functions: bool = False
    ) -> tuple[str, dict[str, Any]]:
        """Remove type annotations from multiple variables.

        Args:
            source: The Python source code
            variables: List of variable names to remove annotations from,
                      or None to remove ALL variable annotations
            include_functions: If True and variables=None, also remove function
                              annotations. Currently not implemented.
                              (default: False, only remove variable annotations)

        Returns:
            Tuple of (modified_source, result_info)
            - modified_source: The source with type annotations removed
            - result_info: Dict with keys:
                - "success": bool
                - "removed_count": int (number of annotations removed)
                - "not_found": list[str] (requested but not annotated/found)
                - "skipped": list[str] (variables without values)
                - "total_requested": int

        Example:
            >>> engine = InsertionEngine()
            >>> source = "x: int = 42\\ny: str = 'hi'\\n"
            >>> modified, info = engine.remove_types_bulk(source, None)
            >>> print(info["removed_count"])
            2
        """
        self.logger.info(
            f"Removing type annotations in bulk "
            f"(variables={variables}, include_functions={include_functions})"
        )

        try:
            # Parse source code into CST
            tree = cst.parse_module(source)

            # Find all currently annotated variables
            annotated_info = self._find_annotated_variables(tree)

            # Determine which variables to remove
            if variables is None:
                # Remove all variable annotations
                variables_to_remove = set(annotated_info.keys())
                not_found = []
            else:
                # Remove only specified variables
                variables_to_remove = set(variables)
                # Track which requested variables were not found or not annotated
                not_found = [v for v in variables if v not in annotated_info]

            # Track variables that will be skipped (no value)
            skipped = [
                var
                for var, info in annotated_info.items()
                if var in variables_to_remove and not info["has_value"]
            ]

            # Create transformer
            # Pass None if removing all, otherwise pass the set
            transformer_arg = None if variables is None else variables_to_remove
            transformer = TypeRemovalTransformer(transformer_arg)

            # Transform the tree
            modified_tree = tree.visit(transformer)

            # Convert back to source code
            modified_source = modified_tree.code

            result_info = {
                "success": transformer.removed_count > 0,
                "removed_count": transformer.removed_count,
                "not_found": not_found,
                "skipped": skipped,
                "total_requested": len(variables) if variables else len(annotated_info),
            }

            self.logger.info(
                f"Bulk removal complete: {transformer.removed_count} removed, "
                f"{len(not_found)} not found, {len(skipped)} skipped"
            )

            return modified_source, result_info

        except Exception as e:
            self.logger.error(f"Error in bulk type removal: {e}", exc_info=True)
            return source, {
                "success": False,
                "removed_count": 0,
                "not_found": variables if variables else [],
                "skipped": [],
                "total_requested": len(variables) if variables else 0,
                "error": str(e),
            }

    def _find_annotated_variables(self, tree: cst.Module) -> dict[str, dict[str, Any]]:
        """Find all variables with type annotations in a module.

        Args:
            tree: The parsed LibCST module

        Returns:
            Mapping of variable names to info dicts:
            {
                "var_name": {
                    "type": "int",
                    "has_value": True,
                    "line": 5
                }
            }
        """
        annotated_vars: dict[str, dict[str, Any]] = {}

        class AnnotationFinder(cst.CSTVisitor):
            def __init__(self) -> None:
                self.current_line = 1

            def visit_AnnAssign(self, node: cst.AnnAssign) -> None:
                if isinstance(node.target, cst.Name):
                    var_name = node.target.value
                    # Get type as string
                    type_str = node.annotation.annotation
                    type_code = cst.Module([]).code_for_node(type_str)

                    annotated_vars[var_name] = {
                        "type": type_code,
                        "has_value": node.value is not None,
                        "line": self.current_line,
                    }

        # Visit the tree to find annotations
        visitor = AnnotationFinder()
        tree.visit(visitor)

        self.logger.debug(f"Found {len(annotated_vars)} annotated variables")
        return annotated_vars

    def preview_removals(self, source: str, variables: list[str] | None = None) -> dict[str, Any]:
        """Preview what type annotations would be removed without modifying source.

        Args:
            source: The Python source code
            variables: List of variable names to preview removal for,
                      or None to preview removal of ALL annotations

        Returns:
            Dict with preview information:
            - "success": bool
            - "will_remove": list[dict] with {"variable": str, "type": str, "line": int}
            - "not_found": list[str] (requested but not annotated)
            - "will_skip": list[dict] with {"variable": str, "reason": str}
            - "total_changes": int

        Example:
            >>> engine = InsertionEngine()
            >>> source = "x: int = 42\\ny: str\\n"
            >>> preview = engine.preview_removals(source, None)
            >>> print(preview["total_changes"])
            1
        """
        self.logger.info(
            f"Generating removal preview for "
            f"{'all variables' if variables is None else f'{len(variables)} variables'}"
        )

        try:
            # Parse source
            tree = cst.parse_module(source)

            # Find all annotated variables
            annotated_info = self._find_annotated_variables(tree)

            # Build preview
            will_remove = []
            will_skip = []
            not_found = []

            if variables is None:
                # Preview removal of all annotations
                for var_name, info in annotated_info.items():
                    if info["has_value"]:
                        will_remove.append(
                            {
                                "variable": var_name,
                                "type": info["type"],
                                "line": info["line"],
                            }
                        )
                    else:
                        will_skip.append(
                            {
                                "variable": var_name,
                                "type": info["type"],
                                "reason": "No value (declaration only)",
                            }
                        )
            else:
                # Preview removal of specific variables
                for var_name in variables:
                    if var_name in annotated_info:
                        info = annotated_info[var_name]
                        if info["has_value"]:
                            will_remove.append(
                                {
                                    "variable": var_name,
                                    "type": info["type"],
                                    "line": info["line"],
                                }
                            )
                        else:
                            will_skip.append(
                                {
                                    "variable": var_name,
                                    "type": info["type"],
                                    "reason": "No value (declaration only)",
                                }
                            )
                    else:
                        not_found.append(var_name)

            return {
                "success": True,
                "will_remove": will_remove,
                "not_found": not_found,
                "will_skip": will_skip,
                "total_changes": len(will_remove),
            }

        except Exception as e:
            self.logger.error(f"Error generating removal preview: {e}", exc_info=True)
            return {
                "success": False,
                "will_remove": [],
                "not_found": [],
                "will_skip": [],
                "total_changes": 0,
                "error": str(e),
            }

    def insert_function_signatures(
        self,
        source: str,
        function_annotations: dict[str, dict[str, Any]],
        skip_annotated: bool = True,
    ) -> tuple[str, dict[str, Any]]:
        """Insert type annotations for function signatures.

        Args:
            source: The Python source code
            function_annotations: Dict mapping function names to their annotations.
                Format: {
                    "func_name": {
                        "params": {"param1": "int", "param2": "str"},
                        "return": "bool"
                    }
                }
            skip_annotated: If True, skip parameters/functions already annotated

        Returns:
            Tuple of (modified_source, result_info)
            result_info contains:
                - "success": bool
                - "modified_count": int (number of functions modified)
                - "skipped": list[str] (function names skipped)
        """
        self.logger.info(f"Inserting signatures for {len(function_annotations)} functions")

        try:
            # Parse source
            tree = cst.parse_module(source)

            # Apply transformation
            transformer = FunctionSignatureTransformer(function_annotations)
            modified_tree = tree.visit(transformer)

            # Convert back to source code
            modified_source = modified_tree.code

            result_info = {
                "success": True,
                "modified_count": transformer.modified_count,
                "skipped": [],
            }

            self.logger.info(f"Modified {transformer.modified_count} function signatures")
            return modified_source, result_info

        except Exception as e:
            self.logger.error(f"Error inserting function signatures: {e}", exc_info=True)
            return source, {
                "success": False,
                "modified_count": 0,
                "skipped": [],
                "error": str(e),
            }
