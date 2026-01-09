"""Unified inference engine for Python type inference.

This module provides the main entry point for type inference:
- Scope analysis (building scope tree with all variables and functions)
- Call graph construction (tracking function relationships)
- Contextual inference (all assignments, expressions, parameters, return types)
- Type propagation (bottom-up through call graph)
"""

import ast
from typing import TYPE_CHECKING, Any

from auto_type.analysis import CallGraphBuilder, ScopeAnalyzer
from auto_type.inference.contextual_inference import ContextualInferenceEngine
from auto_type.inference.type_propagation import TypePropagationEngine

if TYPE_CHECKING:
    from auto_type.analysis.types import CallGraph, ScopeTree


class UnifiedInferenceEngine:
    """Main entry point for all type inference.

    Coordinates:
    1. Scope analysis (building scope tree)
    2. Call graph construction
    3. Contextual type inference (module-level variables)
    4. Type propagation (bottom-up through call graph)

    Usage:
        engine = UnifiedInferenceEngine()
        results = engine.infer_types(source_code)

        # Access inferred types
        for scope_id, scope in results.scope_tree.scopes_by_id.items():
            for var_name, type_info in scope.variables.items():
                print(f"{scope_id}.{var_name}: {type_info.type_str}")
    """

    def __init__(self) -> None:
        """Initialize the unified inference engine."""
        self.scope_analyzer = ScopeAnalyzer()

    def infer_types(self, source: str) -> "InferenceResult":
        """Perform complete type inference on Python source code.

        Args:
            source: Python source code string

        Returns:
            InferenceResult with scope tree, call graph, and inferred types
        """
        # Step 1: Build scope tree
        scope_tree = self.scope_analyzer.analyze(source)

        # Step 2: Build call graph
        call_graph_builder = CallGraphBuilder(scope_tree)
        call_graph = call_graph_builder.build()

        # Step 3: Create contextual inference engine
        contextual_engine = ContextualInferenceEngine(scope_tree, call_graph)

        # Step 4: Perform contextual inference for module-level variables
        contextual_engine.infer_module_types(scope_tree.root)

        # Step 5: Perform bottom-up type propagation
        propagation_engine = TypePropagationEngine(scope_tree, call_graph)
        propagation_engine.propagate_types()

        # Step 6: Create and return result
        return InferenceResult(
            scope_tree=scope_tree,
            call_graph=call_graph,
            source=source,
        )

    def infer_variable_types(self, source: str) -> dict[str, str]:
        """Get module-level variable types (compatibility API).

        Returns module-level variables only for backward compatibility
        with insertion/diagnostic code.

        Args:
            source: Python source code

        Returns:
            Dict mapping variable names to type strings (module-level only)
        """
        result = self.infer_types(source)
        types_map: dict[str, str] = {}

        # Extract module-level variables only
        for var_name, type_info in result.scope_tree.root.variables.items():
            if type_info.type_str != "Unknown":
                types_map[var_name] = type_info.type_str

        return types_map

    def infer_from_node(self, node: ast.expr) -> str:
        """Infer type from a single AST node (compatibility API).

        Used by DiagnosticEngine for quick type checking.
        Creates a temporary contextual engine for expression type inference.

        Args:
            node: AST expression node

        Returns:
            Inferred type string ("Unknown" if cannot infer)
        """
        # Create minimal scope tree for expression inference
        from auto_type.analysis.types import Scope, ScopeTree, ScopeType

        # Create a dummy module scope for context
        dummy_module = Scope(
            scope_id="module",
            scope_type=ScopeType.MODULE,
            name="<temp>",
            ast_node=ast.Module(body=[], type_ignores=[]),
        )
        scope_tree = ScopeTree(root=dummy_module)
        scope_tree.add_scope(dummy_module)

        # Create minimal call graph
        from auto_type.analysis.types import CallGraph

        call_graph = CallGraph()

        # Use contextual engine for inference
        contextual_engine = ContextualInferenceEngine(scope_tree, call_graph)
        return contextual_engine.infer_expression_type(node)


class InferenceResult:
    """Result of type inference containing all inferred information.

    Attributes:
        scope_tree: Scope tree with all scopes and their types
        call_graph: Call graph showing function relationships
        source: Original source code
    """

    def __init__(
        self,
        scope_tree: "ScopeTree",
        call_graph: "CallGraph",
        source: str,
    ) -> None:
        """Initialize inference result.

        Args:
            scope_tree: The analyzed scope tree
            call_graph: The constructed call graph
            source: Original source code
        """
        self.scope_tree = scope_tree
        self.call_graph = call_graph
        self.source = source

    def get_all_type_hints(self) -> dict[str, dict[str, str]]:
        """Get all inferred type hints organized by scope.

        Returns:
            Dictionary mapping scope_id to {var_name: type_str}
        """
        result: dict[str, dict[str, str]] = {}

        for scope_id, scope in self.scope_tree.scopes_by_id.items():
            scope_types: dict[str, str] = {}

            # Add variable types
            for var_name, type_info in scope.variables.items():
                if type_info.type_str != "Unknown":
                    scope_types[var_name] = type_info.type_str

            # Add parameter types
            for param_name, type_info in scope.parameters.items():
                if type_info.type_str != "Unknown":
                    scope_types[f"param:{param_name}"] = type_info.type_str

            # Add return type
            if scope.return_type and scope.return_type.type_str != "Unknown":
                scope_types["return"] = scope.return_type.type_str

            if scope_types:
                result[scope_id] = scope_types

        return result

    def get_function_signatures(self) -> dict[str, str]:
        """Get inferred function signatures.

        Returns:
            Dictionary mapping function scope_id to signature string
        """
        signatures: dict[str, str] = {}

        for func_id, func_node in self.call_graph.functions.items():
            scope = func_node.scope

            # Build parameter list
            params: list[str] = []
            for param_name, type_info in scope.parameters.items():
                if type_info.type_str != "Unknown":
                    params.append(f"{param_name}: {type_info.type_str}")
                else:
                    params.append(param_name)

            # Build return type
            if scope.return_type and scope.return_type.type_str != "Unknown":
                return_type = f" -> {scope.return_type.type_str}"
            else:
                return_type = ""

            # Construct signature
            signatures[func_id] = f"({', '.join(params)}){return_type}"

        return signatures

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

        # Extract function signatures
        for func_id, func_node in self.call_graph.functions.items():
            scope = func_node.scope

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
