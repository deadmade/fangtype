"""Inference result data structures.

This module contains the InferenceResult class which holds type inference results.
"""

import ast
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from auto_type.analysis.types import ScopeTree


class InferenceResult:
    """Result of type inference containing all inferred information.

    Attributes:
        scope_tree: Scope tree with all scopes and their types
        source: Original source code
    """

    def __init__(
        self,
        scope_tree: "ScopeTree",
        source: str,
    ) -> None:
        """Initialize inference result.

        Args:
            scope_tree: The analyzed scope tree
            source: Original source code
        """
        self.scope_tree = scope_tree
        self.source = source

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

        # Helper to check if a variable already has annotation in source
        def has_annotation_in_source(var_name: str, line: int) -> bool:
            """Check if a variable already has a type annotation in the source."""
            lines = self.source.split("\n")
            if 0 <= line < len(lines):
                line_content = lines[line]
                # Remove comments to avoid false positives
                comment_start = line_content.find("#")
                if comment_start != -1:
                    line_content = line_content[:comment_start]
                line_content = line_content.strip()

                # Check for existing annotation patterns (must be at start of assignment)
                patterns = [
                    f"{var_name}:",  # Simple annotation like "x:"
                    f"{var_name} :",  # With space like "x :"
                ]
                return any(
                    line_content.startswith(pattern) or f" {pattern}" in line_content
                    for pattern in patterns
                )
            return False

        # Process all scopes for variables
        for scope in self.scope_tree.scopes_by_id.values():
            for var_name, type_info in scope.variables.items():
                # Skip if type is unknown or already has annotation
                if type_info.type_str == "Unknown":
                    continue

                # Use line number as-is (already 0-based)
                line_0_based = type_info.line

                # Skip if variable already has annotation in source
                if has_annotation_in_source(var_name, line_0_based):
                    continue

                # Use the specific line where this variable is assigned
                key = (line_0_based, var_name)
                variable_insertions[key] = type_info.type_str

        return variable_insertions

    def get_function_insertions(self) -> dict[tuple[int, str], dict[str, Any]]:
        """Get all functions that need type annotations, organized by location.

        Returns functions that are missing parameter or return type annotations,
        keyed by their definition location for precise targeting.

        Returns:
            Dict mapping (line_number, func_name) to function signature info.
            Line numbers are 0-based for consistency.
            Each function info contains:
                - "params": dict[str, str] - Parameters needing annotations
                - "return": str | None - Return type if missing
                - "name": str - Function name
        """
        function_insertions: dict[tuple[int, str], dict[str, Any]] = {}

        # Helper to check if function already has complete annotations
        def has_complete_annotations(scope: Any) -> tuple[dict[str, str], str | None]:
            """Check which annotations are missing for a function."""
            missing_params = {}
            missing_return = None

            # Check parameters
            for param_name, type_info in scope.parameters.items():
                if type_info.type_str != "Unknown":
                    # Check if parameter already has annotation in source
                    if not self._param_has_annotation(scope.ast_node, param_name):
                        missing_params[param_name] = type_info.type_str

            # Check return type
            if scope.return_type and scope.return_type.type_str != "Unknown":
                if not self._function_has_return_annotation(scope.ast_node):
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
            try:
                # For function nodes, get the line number
                if hasattr(scope.ast_node, "lineno"):
                    line_0_based = scope.ast_node.lineno - 1
            except (AttributeError, TypeError):
                line_0_based = 0

            # Create function insertion info
            key = (line_0_based, func_name)
            function_insertions[key] = {
                "name": func_name,
                "params": missing_params,
                "return": missing_return,
            }

        return function_insertions

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

    def get_all_insertable_types(self) -> dict[str, Any]:
        """Get all types that can be inserted as annotations.

        Returns:
            Dict with:
                - "module_vars": dict[str, str] - Module-level variables
                - "functions": dict[str, dict] - Function signatures
                    Each function dict has:
                        - "params": dict[str, str] - Parameter types
                        - "return": str - Return type
                        - "name": str - Function name (extracted from scope_id)
        """
        result: dict[str, Any] = {
            "module_vars": {},
            "functions": {},
        }

        # Extract module-level variables
        for var_name, type_info in self.scope_tree.root.variables.items():
            if type_info.type_str != "Unknown":
                result["module_vars"][var_name] = type_info.type_str

        for scope in self.scope_tree.get_all_function_scopes():
            func_id = scope.scope_id

            # Extract function name from scope_id
            # Format: "func:name" or "func:name#1" or "class:Class.method"
            if ":" not in func_id:
                continue

            name_part = func_id.split(":", 1)[1]
            # Remove lambda counter suffix if present
            if "#" in name_part:
                name_part = name_part.split("#")[0]
            # For class methods, take the method name
            if "." in name_part:
                name_part = name_part.split(".")[-1]

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
                "return": return_type,
            }

        return result
