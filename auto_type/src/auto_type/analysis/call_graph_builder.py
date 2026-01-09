"""Call graph builder for analyzing function call relationships.

This module provides functionality to build a directed call graph showing which
functions call which other functions within a Python module.
"""

import ast

from auto_type.analysis.types import CallGraph, Scope, ScopeTree, ScopeType


class CallGraphBuilder:
    """Builds a call graph from a scope tree.

    Analyzes function bodies to identify function calls and constructs a directed
    graph showing the call relationships. Supports topological sorting for
    bottom-up type inference.

    Attributes:
        scope_tree: The scope tree to analyze
        call_graph: The resulting call graph
        current_function_scope: Current function scope being analyzed
    """

    def __init__(self, scope_tree: ScopeTree) -> None:
        """Initialize the call graph builder.

        Args:
            scope_tree: Scope tree containing all scopes in the module
        """
        self.scope_tree = scope_tree
        self.call_graph = CallGraph()
        self.current_function_scope: Scope | None = None

    def build(self) -> CallGraph:
        """Build the call graph by analyzing all function scopes.

        Returns:
            Complete call graph with all function relationships
        """
        # Add all function scopes to the call graph
        for func_scope in self.scope_tree.get_all_function_scopes():
            self.call_graph.add_function(func_scope)

        # Analyze each function to find calls
        for func_scope in self.scope_tree.get_all_function_scopes():
            self._analyze_function(func_scope)

        return self.call_graph

    def _analyze_function(self, func_scope: Scope) -> None:
        """Analyze a function scope to identify all function calls.

        Args:
            func_scope: Function scope to analyze
        """
        self.current_function_scope = func_scope

        # Visit the function's AST to find all Call nodes
        visitor = _CallVisitor(self)

        if func_scope.ast_node:
            if isinstance(func_scope.ast_node, ast.FunctionDef | ast.AsyncFunctionDef):
                # Regular function - visit body statements
                for stmt in func_scope.ast_node.body:
                    visitor.visit(stmt)
            elif isinstance(func_scope.ast_node, ast.Lambda):
                # Lambda - visit the body expression
                visitor.visit(func_scope.ast_node.body)

        self.current_function_scope = None

    def _record_call(self, call_node: ast.Call) -> None:
        """Record a function call in the call graph.

        Args:
            call_node: AST Call node representing the function call
        """
        if not self.current_function_scope:
            return

        # Try to resolve the called function name
        called_name = self._resolve_function_name(call_node.func)
        if not called_name:
            return

        # Look up the called function in our scope tree
        called_scope_id = self._lookup_function_scope_id(called_name)
        if not called_scope_id:
            return

        # Only record calls to functions we're tracking
        if called_scope_id in self.call_graph.nodes:
            self.call_graph.add_call(self.current_function_scope.scope_id, called_scope_id)

    def _resolve_function_name(self, func_node: ast.expr) -> str | None:
        """Resolve the name of a called function from an AST node.

        Handles simple cases:
        - Direct function calls: foo()
        - Method calls on self: self.method()

        Args:
            func_node: AST node representing the function being called

        Returns:
            Function name if resolvable, None otherwise
        """
        match func_node:
            case ast.Name(id=name):
                # Simple function call: foo()
                return name
            case ast.Attribute(value=ast.Name(id="self"), attr=method_name):
                # Method call on self: self.method()
                return method_name
            case _:
                # Too complex to resolve (chained calls, computed names, etc.)
                return None

    def _lookup_function_scope_id(self, func_name: str) -> str | None:
        """Look up the scope ID for a function by name.

        Searches in the current function's scope and parent scopes to find
        a function with the given name.

        Args:
            func_name: Name of the function to find

        Returns:
            Scope ID if found, None otherwise
        """
        if not self.current_function_scope:
            return None

        # First check children of current scope (nested functions)
        for child in self.current_function_scope.children:
            if (
                child.scope_type in (ScopeType.FUNCTION, ScopeType.LAMBDA)
                and child.name == func_name
            ):
                return child.scope_id

        # Then search parent scopes and their children
        search_scope = self.current_function_scope.parent
        while search_scope:
            # Check children of this scope for a function with matching name
            for child in search_scope.children:
                if (
                    child.scope_type in (ScopeType.FUNCTION, ScopeType.LAMBDA)
                    and child.name == func_name
                ):
                    return child.scope_id

                # Also check for methods in class scopes
                if child.scope_type == ScopeType.CLASS:
                    for class_child in child.children:
                        if (
                            class_child.scope_type in (ScopeType.FUNCTION, ScopeType.LAMBDA)
                            and class_child.name == func_name
                        ):
                            return class_child.scope_id

            # Move up to parent scope
            search_scope = search_scope.parent

        return None


class _CallVisitor(ast.NodeVisitor):
    """AST visitor to find function calls within a function body.

    Attributes:
        builder: The CallGraphBuilder instance
    """

    def __init__(self, builder: CallGraphBuilder) -> None:
        """Initialize the call visitor.

        Args:
            builder: CallGraphBuilder to record calls to
        """
        self.builder = builder

    def visit_Call(self, node: ast.Call) -> None:
        """Visit a function call node.

        Args:
            node: Call AST node
        """
        self.builder._record_call(node)
        # Continue visiting child nodes
        self.generic_visit(node)
