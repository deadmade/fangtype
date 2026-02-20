"""Core data structures for scope-aware type inference.

This module defines the fundamental data structures used throughout the
scope-aware type inference system:

- Type metadata (TypeInfo, TypeSource)
- Scope representation (Scope, ScopeType, ScopeTree)
- Call graph structures (FunctionNode, CallGraph)
"""

import ast
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Protocol, runtime_checkable


@runtime_checkable
class HasLineRange(Protocol):
    """Protocol for AST nodes that expose line range info."""

    lineno: int
    end_lineno: int | None


class ScopeType(Enum):
    """Type of scope in Python code."""

    MODULE = "module"
    FUNCTION = "function"
    CLASS = "class"
    LAMBDA = "lambda"
    COMPREHENSION = "comprehension"


class TypeSource(Enum):
    """Source of inferred type information."""

    LITERAL = "literal"  # From literal value: x = 42
    PARAMETER_USAGE = "param_usage"  # From how param is used: x + 5
    RETURN_VALUE = "return_value"  # From return statement
    FUNCTION_CALL = "function_call"  # From calling function: x = foo()
    UNKNOWN = "unknown"  # Type could not be inferred


@dataclass
class TypeInfo:
    """Information about an inferred type.

    Attributes:
        type_str: String representation of the type (e.g., "int", "str")
        source: How this type was inferred
        line: 0-based line number where the type originates
        col: 0-based column offset
        ast_node: Optional original AST node for the typed element
    """

    type_str: str
    source: TypeSource
    line: int
    col: int
    ast_node: ast.AST | None = None


@dataclass
class Scope:
    """Represents a scope in Python code.

    A scope tracks variables, parameters, and nested scopes. Supports
    lexical scoping rules for variable lookup. Variables are tracked
    flow-sensitively (all assignments with line numbers).

    Attributes:
        scope_id: Unique identifier (e.g., "module", "func:calculate")
        scope_type: Type of scope (module, function, class, etc.)
        name: Human-readable name
        ast_node: Original AST node that defines this scope
        parent: Parent scope in the hierarchy (None for module)
        children: List of nested scopes
        variable_history: All variable assignments in this scope (flow-sensitive)
        parameters: Function parameters (for function scopes)
        return_type: Inferred return type (for function scopes)
        attributes: Class attributes (for class scopes)
        methods: Method scope IDs (for class scopes)
    """

    # Identification
    scope_id: str
    scope_type: ScopeType
    name: str

    # AST node
    ast_node: ast.AST

    # Hierarchy
    parent: Scope | None = None
    children: list[Scope] = field(default_factory=list)

    # Variables and types in this scope (flow-sensitive tracking)
    variable_history: dict[str, list[TypeInfo]] = field(default_factory=dict)

    # For function scopes
    parameters: dict[str, TypeInfo] = field(default_factory=dict)
    return_type: TypeInfo | None = None

    # For class scopes
    attributes: dict[str, TypeInfo] = field(default_factory=dict)
    methods: list[str] = field(default_factory=list)  # List of method scope_ids

    def get_qualified_name(self) -> str:
        """Get fully qualified name like 'module.ClassName.method'.

        Returns:
            Dot-separated qualified name from module root
        """
        if self.parent is None or self.parent.scope_type == ScopeType.MODULE:
            return self.name
        return f"{self.parent.get_qualified_name()}.{self.name}"

    def lookup_variable(self, var_name: str) -> TypeInfo | None:
        """Lookup variable in this scope or parent scopes (lexical scoping).

        Returns the most recent (last) assignment for the variable.
        Follows Python's LEGB rule (Local, Enclosing, Global, Built-in).
        Note: This only handles Local, Enclosing, and Global (module) scopes.

        Args:
            var_name: Name of the variable to look up

        Returns:
            TypeInfo of most recent assignment if found, None otherwise
        """
        # Check local variables first - get LAST assignment
        if self.variable_history.get(var_name):
            return self.variable_history[var_name][-1]

        # Check parameters (for function scopes)
        if var_name in self.parameters:
            return self.parameters[var_name]

        # Check parent scope (enclosing/global)
        if self.parent:
            return self.parent.lookup_variable(var_name)

        return None

    def add_variable(self, var_name: str, type_info: TypeInfo) -> None:
        """Add or track a variable assignment in this scope (flow-sensitive).

        Each assignment is recorded in the variable's history, allowing
        queries for the type at specific line numbers.

        Args:
            var_name: Name of the variable
            type_info: Type information for this assignment
        """
        if var_name not in self.variable_history:
            self.variable_history[var_name] = []
        self.variable_history[var_name].append(type_info)

    def add_parameter(self, param_name: str, type_info: TypeInfo) -> None:
        """Add a parameter to this function scope.

        Args:
            param_name: Name of the parameter
            type_info: Type information for the parameter
        """
        self.parameters[param_name] = type_info

    @property
    def variables(self) -> dict[str, TypeInfo]:
        """Get current (most recent) type for each variable.

        Provides backward-compatible dict interface where each variable
        maps to its most recent (last) assignment's type.

        Returns:
            Dict mapping variable names to their current (last) TypeInfo
        """
        return {
            name: types[-1]
            for name, types in self.variable_history.items()
            if types  # Only include variables with at least one assignment
        }

    def get_variable_type_at_line(self, var_name: str, line: int) -> TypeInfo | None:
        """Get the type of a variable at a specific line number (flow-sensitive).

        Returns the type from the most recent assignment on or before the given line.
        This enables flow-sensitive type queries where variable types can change
        over the course of execution.

        Args:
            var_name: Variable name to look up
            line: 0-based line number where we want to know the type

        Returns:
            TypeInfo for the variable at that line, or None if not found

        Example:
            >>> # source code:
            >>> # line 0: x = 1
            >>> # line 1: y = x + x
            >>> # line 2: x = "hello"
            >>> # line 3: z = x + x
            >>> scope.get_variable_type_at_line("x", 1)  # Returns int
            >>> scope.get_variable_type_at_line("x", 3)  # Returns str
        """
        if var_name not in self.variable_history:
            # Try parent scopes
            if self.parent:
                return self.parent.get_variable_type_at_line(var_name, line)
            return None

        # Find all assignments at or before this line
        candidates = [ti for ti in self.variable_history[var_name] if ti.line <= line]

        if not candidates:
            # No assignments before this line - check parent scope
            if self.parent:
                return self.parent.get_variable_type_at_line(var_name, line)
            return None

        # Return the most recent one (last in filtered list)
        return candidates[-1]


@dataclass
class ScopeTree:
    """Tree of all scopes in a module.

    Provides centralized access to all scopes and their relationships.

    Attributes:
        root: Module-level scope (root of the tree)
        scopes_by_id: Dictionary mapping scope_id to Scope for fast lookup
    """

    root: Scope
    scopes_by_id: dict[str, Scope] = field(default_factory=dict)

    def add_scope(self, scope: Scope) -> None:
        """Register a scope in the tree.

        Args:
            scope: Scope to register
        """
        self.scopes_by_id[scope.scope_id] = scope

    def get_all_function_scopes(self) -> list[Scope]:
        """Get all function and lambda scopes in the tree.

        Returns:
            List of all scopes with scope_type == FUNCTION or LAMBDA
        """
        return [
            scope
            for scope in self.scopes_by_id.values()
            if scope.scope_type in (ScopeType.FUNCTION, ScopeType.LAMBDA)
        ]

    def _node_line_range(self, node: ast.AST) -> tuple[int, int] | None:
        """Return 0-based start/end line range for an AST node, if available."""
        if not isinstance(node, HasLineRange):
            return None
        start_line = node.lineno - 1
        end_line = node.end_lineno - 1 if node.end_lineno is not None else start_line
        return start_line, end_line

    def find_scope_for_line(self, line: int) -> Scope:
        """Find the innermost scope that contains a given line number.

        Args:
            line: 0-based line number

        Returns:
            The most specific scope containing this line (defaults to root)
        """
        best_scope = self.root

        for scope in self.scopes_by_id.values():
            if scope.scope_type == ScopeType.MODULE:
                continue

            # Check if this scope's AST node contains the line
            ast_node = scope.ast_node
            line_range = self._node_line_range(ast_node)
            if line_range is None:
                continue
            start_line, end_line = line_range

            # This scope contains the line - check if it's more specific
            if start_line <= line <= end_line:
                best_range = self._node_line_range(best_scope.ast_node)
                best_start = best_range[0] if best_range is not None else -1
                if best_scope.scope_type == ScopeType.MODULE or start_line >= best_start:
                    best_scope = scope

        return best_scope

    def get_variable_type_at_line(self, var_name: str, line: int) -> TypeInfo | None:
        """Get the type of a variable at a specific line number across all scopes.

        This method finds the appropriate scope for the given line and queries
        the variable type there, properly handling nested function scopes.

        Args:
            var_name: Variable name to look up
            line: 0-based line number

        Returns:
            TypeInfo for the variable at that line, or None if not found
        """
        # Find the scope that contains this line
        scope = self.find_scope_for_line(line)

        # Query the variable type in that scope
        return scope.get_variable_type_at_line(var_name, line)

    def get_function_scope_by_qualified_name(self, qualified_name: str) -> Scope | None:
        """Find function scope by qualified name (e.g., 'MyClass.method', 'A.B.method').

        Args:
            qualified_name: Function name, possibly qualified (e.g., 'func', 'Class.method')

        Returns:
            The matching function scope, or None if not found
        """
        parts = qualified_name.split(".")

        if len(parts) == 1:
            # Simple function name - return first match
            for scope in self.get_all_function_scopes():
                if scope.name == parts[0]:
                    return scope
            return None

        # Qualified name: Class.method or A.B.method
        method_name = parts[-1]
        class_path = parts[:-1]

        for scope in self.get_all_function_scopes():
            if scope.name == method_name:
                # Verify parent hierarchy matches the class path
                parent = scope.parent
                match = True
                for class_name in reversed(class_path):
                    if parent and parent.name == class_name:
                        parent = parent.parent
                    else:
                        match = False
                        break

                if match:
                    return scope

        return None

    def get_class_scope_for_function_scope(self, function_scope: Scope) -> Scope | None:
        """Get the owning class scope for a function scope.

        Args:
            function_scope: Function scope to inspect

        Returns:
            The direct parent class scope if the function belongs to a class,
            otherwise None.
        """
        if function_scope.scope_type != ScopeType.FUNCTION:
            return None

        parent = function_scope.parent
        if parent and parent.scope_type == ScopeType.CLASS:
            return parent
        return None

    def get_attribute_type_for_method_context(
        self, function_scope: Scope, attr_name: str, line: int
    ) -> TypeInfo | None:
        """Resolve a ``self`` attribute type from method and class context.

        Lookup order:
        1. Method-local tracked attributes.
        2. Owning class tracked attributes.
        3. Sibling method attributes in the same class.

        Args:
            function_scope: Method scope where lookup happens
            attr_name: Attribute name without ``self.`` prefix
            line: 0-based line number for context

        Returns:
            Resolved TypeInfo or None when unresolved.
        """
        attr = function_scope.attributes.get(attr_name)
        if attr and attr.type_str != "Unknown":
            return attr

        class_scope = self.get_class_scope_for_function_scope(function_scope)
        if class_scope is None:
            return None

        class_attr = class_scope.attributes.get(attr_name)
        if class_attr and class_attr.type_str != "Unknown" and class_attr.line <= line:
            return class_attr

        for sibling in class_scope.children:
            if sibling.scope_type != ScopeType.FUNCTION:
                continue
            sibling_attr = sibling.attributes.get(attr_name)
            if sibling_attr and sibling_attr.type_str != "Unknown" and sibling_attr.line <= line:
                return sibling_attr

        return None


@dataclass
class FunctionNode:
    """Node in the call graph representing a function.

    Tracks which functions this function calls and which functions call it.

    Attributes:
        scope: The function's scope from the scope tree
        calls: List of scope_ids for functions this function calls
        called_by: List of scope_ids for functions that call this function
    """

    scope: Scope
    calls: list[str] = field(default_factory=list)
    called_by: list[str] = field(default_factory=list)


@dataclass
class CallGraph:
    """Directed graph of function calls within a module.

    Tracks which functions call which other functions, enabling bottom-up
    type inference by processing functions in topological order.

    Attributes:
        nodes: Dictionary mapping scope_id to FunctionNode
    """

    nodes: dict[str, FunctionNode] = field(default_factory=dict)

    @property
    def functions(self) -> dict[str, FunctionNode]:
        """Alias for nodes for more intuitive API.

        Returns:
            Dictionary mapping scope_id to FunctionNode
        """
        return self.nodes

    def add_function(self, scope: Scope) -> FunctionNode:
        """Add a function to the call graph.

        Args:
            scope: Function scope to add

        Returns:
            The created FunctionNode
        """
        node = FunctionNode(scope=scope)
        self.nodes[scope.scope_id] = node
        return node

    def add_call(self, caller_id: str, callee_id: str) -> None:
        """Add a call edge from caller to callee.

        Args:
            caller_id: Scope ID of the calling function
            callee_id: Scope ID of the called function
        """
        if caller_id in self.nodes and callee_id in self.nodes:
            if callee_id not in self.nodes[caller_id].calls:
                self.nodes[caller_id].calls.append(callee_id)
            if caller_id not in self.nodes[callee_id].called_by:
                self.nodes[callee_id].called_by.append(caller_id)

    def get_topological_levels(self) -> list[list[FunctionNode]]:
        """Group functions into levels for bottom-up processing.

        Uses a modified Kahn's algorithm to group functions into levels:
        - Level 0: Leaf functions (no outgoing calls)
        - Level i: Functions that only call functions from levels 0..i-1

        Handles cycles (recursive/mutually recursive functions) by grouping
        them together in the same level.

        Returns:
            List of levels, where each level is a list of FunctionNode.
            Functions should be processed level-by-level from 0 to N.
        """
        # Build in-degree map (how many unprocessed functions this function calls)
        levels: list[list[FunctionNode]] = []
        processed: set[str] = set()

        while len(processed) < len(self.nodes):
            # Find all nodes with in-degree 0 (considering only unprocessed callees)
            current_level: list[FunctionNode] = []

            for node_id, node in self.nodes.items():
                if node_id not in processed:
                    # Count unprocessed callees
                    unprocessed_calls = [c for c in node.calls if c not in processed]
                    if len(unprocessed_calls) == 0:
                        current_level.append(node)

            if not current_level:
                # Cycle detected - add all remaining as one level
                # This handles recursive and mutually recursive functions
                current_level = [
                    node for node_id, node in self.nodes.items() if node_id not in processed
                ]

            if current_level:
                levels.append(current_level)
                processed.update(node.scope.scope_id for node in current_level)

        return levels
