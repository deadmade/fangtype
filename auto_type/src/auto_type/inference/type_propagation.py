"""Type propagation engine for bottom-up type inference.

This module coordinates the bottom-up type inference process:
1. Analyze functions in topological order (leaves first)
2. Propagate type information from callees to callers
3. Infer parameter types from call sites
"""

import ast

from auto_type.analysis.types import CallGraph, Scope, ScopeTree, TypeInfo, TypeSource
from auto_type.inference.contextual_inference import ContextualInferenceEngine


class TypePropagationEngine:
    """Orchestrates bottom-up type inference through the call graph.

    This engine:
    - Processes functions in topological order (leaves first)
    - Infers return types for leaf functions first
    - Propagates type information up through callers
    - Infers parameter types from how functions are called

    Attributes:
        scope_tree: The scope tree with all scopes
        call_graph: The call graph showing function relationships
        contextual_engine: Engine for inferring types within functions
        inferred_params: Cache of inferred parameter types
    """

    def __init__(self, scope_tree: ScopeTree, call_graph: CallGraph) -> None:
        """Initialize the propagation engine.

        Args:
            scope_tree: Scope tree with all scopes
            call_graph: Call graph with function relationships
        """
        self.scope_tree = scope_tree
        self.call_graph = call_graph
        self.contextual_engine = ContextualInferenceEngine(scope_tree, call_graph)
        self.inferred_params: dict[str, dict[str, str]] = {}

    def propagate_types(self) -> None:
        """Perform bottom-up type propagation through the call graph.

        This is the main entry point for type inference.
        """
        # Get topological levels (leaf functions first)
        levels = self.call_graph.topological_levels()

        # Process each level bottom-up
        for level in levels:
            for func_id in level:
                func_node = self.call_graph.functions.get(func_id)
                if func_node:
                    self._infer_function_types(func_node.scope)

    def _infer_function_types(self, func_scope: Scope) -> None:
        """Infer types for a single function.

        Args:
            func_scope: Function scope to analyze
        """
        # First, try to infer parameter types from call sites
        self._infer_parameter_types_from_calls(func_scope)

        # Then infer types within the function body
        self.contextual_engine.infer_function_types(func_scope)

    def _infer_parameter_types_from_calls(self, func_scope: Scope) -> None:
        """Infer parameter types by analyzing how the function is called.

        Args:
            func_scope: Function scope
        """
        func_id = func_scope.scope_id
        func_node = self.call_graph.functions.get(func_id)

        if not func_node or not func_node.called_by:
            return

        # Find all call sites for this function
        param_types: dict[str, set[str]] = {}

        for caller_id in func_node.called_by:
            caller_node = self.call_graph.functions.get(caller_id)
            if not caller_node:
                continue

            caller_scope = caller_node.scope

            # Find calls to this function in the caller's body
            call_analyzer = _CallSiteAnalyzer(func_scope.name, self.contextual_engine)

            if caller_scope.ast_node:
                if isinstance(caller_scope.ast_node, ast.FunctionDef | ast.AsyncFunctionDef):
                    for stmt in caller_scope.ast_node.body:
                        call_analyzer.visit(stmt)
                elif isinstance(caller_scope.ast_node, ast.Lambda):
                    call_analyzer.visit(caller_scope.ast_node.body)

            # Collect argument types from all call sites
            for call_site in call_analyzer.call_sites:
                arg_types = call_site.get("arg_types", [])
                param_names = list(func_scope.parameters.keys())

                for i, arg_type in enumerate(arg_types):
                    if i < len(param_names) and arg_type:
                        param_name = param_names[i]
                        if param_name not in param_types:
                            param_types[param_name] = set()
                        param_types[param_name].add(arg_type)

        # Update parameter types
        for param_name, types in param_types.items():
            if types:
                type_str = types.pop() if len(types) == 1 else " | ".join(sorted(types))

                # Update the parameter type
                func_scope.parameters[param_name] = TypeInfo(
                    type_str=type_str,
                    source=TypeSource.PARAMETER_USAGE,
                    line=func_scope.parameters[param_name].line,
                    col=func_scope.parameters[param_name].col,
                    ast_node=func_scope.parameters[param_name].ast_node,
                )


class _CallSiteAnalyzer(ast.NodeVisitor):
    """Analyzes call sites to extract argument type information.

    Attributes:
        target_func_name: Name of the function we're looking for
        inference_engine: Engine to infer expression types
        call_sites: List of found call sites with argument types
    """

    def __init__(self, target_func_name: str, inference_engine: ContextualInferenceEngine) -> None:
        """Initialize the call site analyzer.

        Args:
            target_func_name: Name of function to find calls to
            inference_engine: Engine for type inference
        """
        self.target_func_name = target_func_name
        self.inference_engine = inference_engine
        self.call_sites: list[dict[str, list[str | None]]] = []

    def visit_Call(self, node: ast.Call) -> None:
        """Visit a call node and check if it's calling our target function.

        Args:
            node: Call AST node
        """
        # Check if this is a call to our target function
        is_target = False

        match node.func:
            case ast.Name(id=name):
                is_target = name == self.target_func_name
            case ast.Attribute(value=ast.Name(id="self"), attr=method_name):
                is_target = method_name == self.target_func_name

        if is_target:
            # Infer types of arguments
            arg_types: list[str | None] = []

            # Create a temporary visitor to infer types
            from auto_type.inference.contextual_inference import _TypeInferenceVisitor

            visitor = _TypeInferenceVisitor(self.inference_engine)

            for arg in node.args:
                arg_type = visitor.infer_expression_type(arg)
                arg_types.append(arg_type)

            self.call_sites.append({"arg_types": arg_types})

        self.generic_visit(node)
