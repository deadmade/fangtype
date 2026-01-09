"""Contextual type inference engine for analyzing function bodies.

This module provides the ContextualInferenceEngine which infers types for:
- Variables within function bodies
- Function return types based on return statements
- Function parameter types based on how they're used
"""

import ast

from auto_type.analysis.types import CallGraph, Scope, ScopeTree, TypeInfo, TypeSource
from auto_type.inference._type_helpers import infer_binop_result_type


class ContextualInferenceEngine:
    """Infers types for variables, parameters, and return types within functions.

    Uses contextual analysis to infer types based on:
    - Literal assignments
    - Operation usage (arithmetic, comparisons, etc.)
    - Method calls
    - Return statements
    - Parameter usage patterns

    Attributes:
        scope_tree: The scope tree containing all scopes
        call_graph: The call graph for function relationships
        current_scope: Current scope being analyzed
    """

    def __init__(self, scope_tree: ScopeTree, call_graph: CallGraph) -> None:
        """Initialize the contextual inference engine.

        Args:
            scope_tree: Scope tree with all scopes
            call_graph: Call graph with function relationships
        """
        self.scope_tree = scope_tree
        self.call_graph = call_graph
        self.current_scope: Scope | None = None

    def infer_module_types(self, module_scope: Scope) -> None:
        """Infer types for module-level variables.

        This analyzes all module-level assignments and updates the module scope
        with inferred types.

        Args:
            module_scope: Module scope to analyze
        """
        self.current_scope = module_scope

        if not module_scope.ast_node:
            return

        # Module ast_node should be ast.Module
        if isinstance(module_scope.ast_node, ast.Module):
            visitor = _TypeInferenceVisitor(self)
            for stmt in module_scope.ast_node.body:
                # Skip function and class definitions - they will be handled separately
                if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                    continue
                visitor.visit(stmt)

        self.current_scope = None

    def infer_function_types(self, func_scope: Scope) -> None:
        """Infer all types within a function scope.

        This includes:
        - Local variable types
        - Parameter types (from usage)
        - Return type (from return statements)

        Args:
            func_scope: Function scope to analyze
        """
        self.current_scope = func_scope

        if not func_scope.ast_node:
            return

        # Handle different function types
        if isinstance(func_scope.ast_node, ast.FunctionDef | ast.AsyncFunctionDef):
            # Analyze function body
            visitor = _TypeInferenceVisitor(self)
            for stmt in func_scope.ast_node.body:
                visitor.visit(stmt)

            # Infer return type from collected return statements
            self._infer_return_type(func_scope, visitor.return_statements)

        elif isinstance(func_scope.ast_node, ast.Lambda):
            # Analyze lambda body
            visitor = _TypeInferenceVisitor(self)
            visitor.visit(func_scope.ast_node.body)

            # Lambda return type is the type of the body expression
            return_type = visitor.infer_expression_type(func_scope.ast_node.body)
            if return_type:
                func_scope.return_type = TypeInfo(
                    type_str=return_type,
                    source=TypeSource.RETURN_VALUE,
                    line=getattr(func_scope.ast_node, "lineno", 1) - 1,
                    col=getattr(func_scope.ast_node, "col_offset", 0),
                    ast_node=func_scope.ast_node,
                )

        self.current_scope = None

    def infer_expression_type(self, node: ast.expr) -> str:
        """Infer type from a single AST expression node.

        Public API for inferring types of individual expressions.
        Used by DiagnosticEngine and other components.

        Args:
            node: AST expression node

        Returns:
            Inferred type string (e.g., "int", "str", "Unknown")
        """
        visitor = _TypeInferenceVisitor(self)
        return visitor.infer_expression_type(node)

    def _infer_return_type(self, func_scope: Scope, return_statements: list[ast.Return]) -> None:
        """Infer function return type from return statements.

        Args:
            func_scope: Function scope
            return_statements: List of return statement nodes
        """
        if not return_statements:
            # No explicit returns - implicit None
            func_scope.return_type = TypeInfo(
                type_str="None",
                source=TypeSource.RETURN_VALUE,
                line=getattr(func_scope.ast_node, "lineno", 1) - 1,
                col=getattr(func_scope.ast_node, "col_offset", 0),
                ast_node=func_scope.ast_node,
            )
            return

        # Collect types from all return statements
        visitor = _TypeInferenceVisitor(self)
        return_types: set[str] = set()

        for ret_stmt in return_statements:
            if ret_stmt.value is None:
                return_types.add("None")
            else:
                ret_type = visitor.infer_expression_type(ret_stmt.value)
                if ret_type != "Unknown":
                    return_types.add(ret_type)

        if not return_types:
            return_type_str = "Unknown"
        elif len(return_types) == 1:
            return_type_str = return_types.pop()
        else:
            # Multiple return types - create union
            return_type_str = " | ".join(sorted(return_types))

        ast_node = func_scope.ast_node
        func_scope.return_type = TypeInfo(
            type_str=return_type_str,
            source=TypeSource.RETURN_VALUE,
            line=(getattr(ast_node, "lineno", 1) - 1) if ast_node else 0,
            col=getattr(ast_node, "col_offset", 0) if ast_node else 0,
            ast_node=ast_node,
        )


class _TypeInferenceVisitor(ast.NodeVisitor):
    """AST visitor for inferring types within a function body.

    Attributes:
        engine: The ContextualInferenceEngine instance
        return_statements: Collected return statements
    """

    def __init__(self, engine: ContextualInferenceEngine) -> None:
        """Initialize the visitor.

        Args:
            engine: The inference engine
        """
        self.engine = engine
        self.return_statements: list[ast.Return] = []

    def visit_Assign(self, node: ast.Assign) -> None:
        """Handle variable assignments.

        Args:
            node: Assignment AST node
        """
        # Infer type from the value
        value_type = self.infer_expression_type(node.value)

        if self.engine.current_scope:
            # Assign to all targets (even if type is "Unknown")
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.engine.current_scope.add_variable(
                        target.id,
                        TypeInfo(
                            type_str=value_type,
                            source=TypeSource.LITERAL,
                            line=node.lineno - 1,
                            col=target.col_offset,
                            ast_node=node,
                        ),
                    )

        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        """Handle augmented assignments (+=, -=, etc.).

        Args:
            node: AugAssign AST node
        """
        # For augmented assignment, target must already have a type
        # We can infer it from the operation
        if isinstance(node.target, ast.Name) and self.engine.current_scope:
            target_name = node.target.id

            # Try to infer from the value being added
            value_type = self.infer_expression_type(node.value)

            # Check if variable already exists
            existing = self.engine.current_scope.lookup_variable(target_name)
            if not existing:
                # Variable doesn't exist yet, infer from value (even if "Unknown")
                self.engine.current_scope.add_variable(
                    target_name,
                    TypeInfo(
                        type_str=value_type,
                        source=TypeSource.LITERAL,
                        line=node.lineno - 1,
                        col=node.target.col_offset,
                        ast_node=node,
                    ),
                )

        self.generic_visit(node)

    def visit_Return(self, node: ast.Return) -> None:
        """Collect return statements for later analysis.

        Args:
            node: Return AST node
        """
        self.return_statements.append(node)
        self.generic_visit(node)

    def infer_expression_type(self, node: ast.expr) -> str:
        """Infer the type of an expression.

        Args:
            node: Expression AST node

        Returns:
            Type string (e.g., "int", "str", "Unknown" for unhandled cases)
        """
        match node:
            # Literals
            case ast.Constant(value=bool()):
                return "bool"
            case ast.Constant(value=int()):
                return "int"
            case ast.Constant(value=float()):
                return "float"
            case ast.Constant(value=str()):
                return "str"
            case ast.Constant(value=bytes()):
                return "bytes"
            case ast.Constant(value=None):
                return "None"

            # Collections
            case ast.List():
                return "list"
            case ast.Dict():
                return "dict"
            case ast.Set():
                return "set"
            case ast.Tuple():
                return "tuple"

            # Binary operations
            case ast.BinOp(left=left, op=op, right=right):
                return self._infer_binop_type(left, op, right)

            # Comparisons always return bool
            case ast.Compare():
                return "bool"

            # Boolean operations return bool
            case ast.BoolOp():
                return "bool"

            # Unary operations
            case ast.UnaryOp(op=ast.Not()):
                return "bool"
            case ast.UnaryOp(op=ast.Invert(), operand=operand):
                # Bitwise NOT (~)
                operand_type = self.infer_expression_type(operand)
                if operand_type in ("int", "bool"):
                    return "int"
                return "Unknown"
            case ast.UnaryOp(operand=operand):
                return self.infer_expression_type(operand)

            # Variable reference
            case ast.Name(id=name):
                return self._lookup_variable_type(name)

            # Function call
            case ast.Call(func=func):
                return self._infer_call_return_type(func)

            # Attribute access
            case ast.Attribute():
                # Can't easily infer attribute types without more context
                return "Unknown"

            # Subscript
            case ast.Subscript():
                # Subscripting a dict/list - would need element type info
                return "Unknown"

            # List/dict/set comprehensions
            case ast.ListComp():
                return "list"
            case ast.DictComp():
                return "dict"
            case ast.SetComp():
                return "set"
            case ast.GeneratorExp():
                return "Generator"

            # If expression
            case ast.IfExp(body=body, orelse=orelse):
                # Try to unify types from both branches
                body_type = self.infer_expression_type(body)
                else_type = self.infer_expression_type(orelse)
                if body_type == else_type:
                    return body_type
                elif body_type != "Unknown" and else_type != "Unknown":
                    return f"{body_type} | {else_type}"
                elif body_type != "Unknown":
                    return body_type
                elif else_type != "Unknown":
                    return else_type
                return "Unknown"

            case _:
                return "Unknown"

    def _infer_binop_type(self, left: ast.expr, op: ast.operator, right: ast.expr) -> str:
        """Infer type from binary operation.

        Args:
            left: Left operand
            op: Operator
            right: Right operand

        Returns:
            Inferred type string ("Unknown" if cannot infer)
        """
        # Infer types of BOTH operands (not just left)
        left_type = self.infer_expression_type(left)
        right_type = self.infer_expression_type(right)

        # Get operator name
        op_name = op.__class__.__name__

        # Use shared helper function
        return infer_binop_result_type(left_type, op_name, right_type)

    def _lookup_variable_type(self, name: str) -> str:
        """Look up the type of a variable by name.

        Args:
            name: Variable name

        Returns:
            Type string if found, "Unknown" otherwise
        """
        if not self.engine.current_scope:
            return "Unknown"

        # Look up in current scope and parent scopes
        type_info = self.engine.current_scope.lookup_variable(name)
        if type_info:
            return type_info.type_str

        # Check if it's a parameter
        if name in self.engine.current_scope.parameters:
            param_type = self.engine.current_scope.parameters[name]
            return param_type.type_str

        return "Unknown"

    def _infer_call_return_type(self, func_node: ast.expr) -> str:
        """Infer return type of a function call.

        Args:
            func_node: Function expression node

        Returns:
            Return type if known, "Unknown" otherwise
        """
        # For now, we'll handle simple cases
        match func_node:
            case ast.Name(id=name):
                # Look up function in scope tree
                func_scope = self._lookup_function_scope(name)
                if func_scope and func_scope.return_type:
                    return func_scope.return_type.type_str

            case ast.Attribute(value=ast.Name(id="self"), attr=method_name):
                # Method call on self
                func_scope = self._lookup_function_scope(method_name)
                if func_scope and func_scope.return_type:
                    return func_scope.return_type.type_str

        # Check for common builtins
        if isinstance(func_node, ast.Name):
            builtin_types = {
                "len": "int",
                "str": "str",
                "int": "int",
                "float": "float",
                "bool": "bool",
                "list": "list",
                "dict": "dict",
                "set": "set",
                "tuple": "tuple",
                "range": "range",
                "enumerate": "enumerate",
                "zip": "zip",
                "map": "map",
                "filter": "filter",
            }
            result = builtin_types.get(func_node.id)
            if result:
                return result

        return "Unknown"

    def _lookup_function_scope(self, func_name: str) -> Scope | None:
        """Look up a function scope by name.

        Args:
            func_name: Function name

        Returns:
            Function scope if found, None otherwise
        """
        if not self.engine.current_scope:
            return None

        # Search in current scope's children first (nested functions)
        for child in self.engine.current_scope.children:
            if child.name == func_name:
                return child

        # Search in parent scopes
        search_scope = self.engine.current_scope.parent
        while search_scope:
            for child in search_scope.children:
                if child.name == func_name:
                    return child
            search_scope = search_scope.parent

        return None
