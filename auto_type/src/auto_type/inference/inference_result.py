"""Inference result data structures.

This module contains the InferenceResult class which holds type inference results.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from auto_type.analysis import Scope, ScopeTree


class FunctionInsertionInfo(TypedDict):
    """Structured function insertion payload."""

    name: str
    params: dict[str, str]
    return_type: str | None


class AllInsertableTypes(TypedDict):
    """All insertable types grouped by category."""

    module_vars: dict[str, str]
    functions: dict[str, FunctionInsertionInfo]


class InferenceResult:
    """Result of type inference containing all inferred information.

    Attributes:
        scope_tree: Scope tree with all scopes and their types
        source: Original source code
    """

    def __init__(
        self,
        scope_tree: ScopeTree,
        source: str,
    ) -> None:
        """Initialize inference result.

        Args:
            scope_tree: The analyzed scope tree
            source: Original source code
        """
        self.scope_tree = scope_tree
        self.source = source
        self._source_lines = source.splitlines()

    def _has_inline_annotation(self, name: str, line_0: int) -> bool:
        """Check if ``name`` is already inline-annotated at ``line_0``."""
        if line_0 < 0 or line_0 >= len(self._source_lines):
            return False

        line_content = self._source_lines[line_0]
        comment_start = line_content.find("#")
        if comment_start != -1:
            line_content = line_content[:comment_start]
        line_content = line_content.strip()

        patterns = [f"{name}:", f"{name} :"]
        return any(
            line_content.startswith(pattern) or f" {pattern}" in line_content
            for pattern in patterns
        )

    def get_variable_insertions(self) -> dict[tuple[int, str], str]:
        """Get all variables that need type annotations, organized by scope.

        Returns variables that don't already have annotations, keyed by their
        location and name for precise scope-aware targeting.

        Returns:
            Dict mapping (line_number, var_name) to type_string.
            Line numbers are 0-based for consistency.
            Only includes variables without existing annotations.
        """
        variable_insertions: dict[tuple[int, str], str] = {}

        # Process all scopes for variables
        for scope in self.scope_tree.scopes_by_id.values():
            for var_name, type_info in scope.variables.items():
                # Skip if type is unknown or already has annotation
                if type_info.type_str == "Unknown":
                    continue

                # Use line number as-is (already 0-based)
                line_0_based = type_info.line

                # Skip if variable already has annotation in source
                if self._has_inline_annotation(var_name, line_0_based):
                    continue

                # Use the specific line where this variable is assigned
                key = (line_0_based, var_name)
                variable_insertions[key] = type_info.type_str

        return variable_insertions

    def get_function_insertions(self) -> dict[tuple[int, str], FunctionInsertionInfo]:
        """Get all functions that need type annotations, organized by location.

        Returns functions that are missing parameter or return type annotations,
        keyed by their definition location for precise targeting.

        Returns:
            Dict mapping (line_number, func_name) to function signature info.
            Line numbers are 0-based for consistency.
            Each function info contains:
                - "params": dict[str, str] - Parameters needing annotations
                - "return_type": str | None - Return type if missing
                - "name": str - Function name
        """
        function_insertions: dict[tuple[int, str], FunctionInsertionInfo] = {}

        # Helper to check if function already has complete annotations
        def has_complete_annotations(scope: Scope) -> tuple[dict[str, str], str | None]:
            """Check which annotations are missing for a function."""
            missing_params = {}
            missing_return = None

            # Check parameters
            for param_name, type_info in scope.parameters.items():
                if type_info.type_str != "Unknown" and not self._param_has_annotation(
                    scope.ast_node, param_name
                ):
                    missing_params[param_name] = type_info.type_str

            # Check return type
            if (
                scope.return_type
                and scope.return_type.type_str != "Unknown"
                and not self._function_has_return_annotation(scope.ast_node)
            ):
                missing_return = scope.return_type.type_str

            return missing_params, missing_return

        # Process all function scopes
        for scope in self.scope_tree.get_all_function_scopes():
            missing_params, missing_return = has_complete_annotations(scope)

            # Skip if function doesn't need any annotations
            if not missing_params and missing_return is None:
                continue

            # Extract function name from scope_id
            func_name = self._extract_function_name(scope.scope_id)

            # Get function definition line (0-based)
            line_0_based = 0  # Default fallback
            if isinstance(scope.ast_node, ast.FunctionDef | ast.AsyncFunctionDef):
                line_0_based = scope.ast_node.lineno - 1

            # Create function insertion info
            key = (line_0_based, func_name)
            function_insertions[key] = {
                "name": func_name,
                "params": missing_params,
                "return_type": missing_return,
            }

        return function_insertions

    def get_attribute_insertions(self) -> dict[tuple[int, str], str]:
        """Get all attributes that need type annotations, organized by scope.

        Returns attributes that don't already have annotations, keyed by their
        location and name for precise scope-aware targeting.

        Returns:
            Dict mapping (line_number, attr_name) to type_string.
            Line numbers are 0-based for consistency.
            Only includes attributes without existing annotations.
            Attribute names include the full path (e.g., "self.width").
        """
        attribute_insertions: dict[tuple[int, str], str] = {}

        # Process all scopes for attributes
        for scope in self.scope_tree.scopes_by_id.values():
            for attr_name, type_info in scope.attributes.items():
                # Skip if type is unknown or already has annotation
                if type_info.type_str == "Unknown":
                    continue

                # Convert to 1-based line number for benchmark compatibility
                line_1_based = type_info.line + 1

                # Skip if attribute already has annotation in source
                if self._has_inline_annotation(attr_name, type_info.line):
                    continue

                # Use the specific line where this attribute is assigned
                key = (line_1_based, attr_name)
                attribute_insertions[key] = type_info.type_str

        return attribute_insertions

    def _param_has_annotation(self, func_node: ast.AST, param_name: str) -> bool:
        """Check if a function parameter already has a type annotation."""
        if not isinstance(func_node, ast.FunctionDef | ast.AsyncFunctionDef):
            return False

        for arg in func_node.args.args:
            if arg.arg == param_name:
                return arg.annotation is not None
        return False

    def _function_has_return_annotation(self, func_node: ast.AST) -> bool:
        """Check if a function already has a return type annotation."""
        if not isinstance(func_node, ast.FunctionDef | ast.AsyncFunctionDef):
            return False
        return func_node.returns is not None

    def _extract_function_name(self, scope_id: str) -> str:
        """Extract clean function name from scope ID."""
        # Format: "func:name" or "func:name#1" or "class:Class.method"
        if ":" not in scope_id:
            return scope_id

        name_part = scope_id.split(":", 1)[1]
        # Remove lambda counter suffix if present
        if "#" in name_part:
            name_part = name_part.split("#")[0]
        # For class methods, take the method name
        if "." in name_part:
            name_part = name_part.split(".")[-1]

        return name_part

    def get_all_insertable_types(self) -> AllInsertableTypes:
        """Get all types that can be inserted as annotations.

        Returns:
            Dict with:
                - "module_vars": dict[str, str] - Module-level variables
                - "functions": dict[str, dict] - Function signatures
                    Each function dict has:
                        - "params": dict[str, str] - Parameter types
                        - "return_type": str - Return type
                        - "name": str - Function name (extracted from scope_id)
        """
        result: AllInsertableTypes = {
            "module_vars": {},
            "functions": {},
        }

        # Extract module-level variables
        for var_name, type_info in self.scope_tree.root.variables.items():
            if type_info.type_str != "Unknown":
                result["module_vars"][var_name] = type_info.type_str

        for scope in self.scope_tree.get_all_function_scopes():
            func_id = scope.scope_id

            if ":" not in func_id:
                continue
            name_part = self._extract_function_name(func_id)

            # Build parameter types
            params: dict[str, str] = {}
            for param_name, type_info in scope.parameters.items():
                if type_info.type_str != "Unknown":
                    params[param_name] = type_info.type_str

            # Get return type
            return_type: str | None = None
            if scope.return_type and scope.return_type.type_str != "Unknown":
                return_type = scope.return_type.type_str

            # Include all functions (even without inferred types) so they can be processed
            result["functions"][func_id] = {
                "name": name_part,
                "params": params,
                "return_type": return_type,
            }

        return result
