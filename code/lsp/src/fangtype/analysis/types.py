"""Core data structures for scope-aware type inference: type metadata, scope, and scope tree."""

import ast
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable


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


class TypeSource(Enum):
    """Source of inferred type information."""

    LITERAL = "literal"  # From literal value: x = 42
    PARAMETER_USAGE = "param_usage"  # From how param is used: x + 5
    RETURN_VALUE = "return_value"  # From return statement
    FUNCTION_CALL = "function_call"  # From calling function: x = foo()
    INHERITED = "inherited"  # From an overridden base-class method signature
    UNKNOWN = "unknown"  # Type could not be inferred


@dataclass
class TypeInfo:
    """Inferred type: type_str, source, 0-based line/col, and optional original AST node."""

    type_str: str
    source: TypeSource
    line: int
    col: int
    ast_node: ast.AST | None = None


@dataclass
class Scope:
    """Scope: flow-sensitive var history, params, attrs; skips global/nonlocal + comprehensions."""

    # Identification
    scope_id: str
    scope_type: ScopeType
    name: str

    # AST node
    ast_node: ast.AST

    # Hierarchy
    parent: "Scope | None" = None
    children: "list[Scope]" = field(default_factory=list)

    # Variables and types in this scope (flow-sensitive tracking)
    variable_history: dict[str, list[TypeInfo]] = field(default_factory=dict)

    # Names declared `global`/`nonlocal` in this scope's own body — cannot be annotated here.
    nonlocal_or_global_names: set[str] = field(default_factory=set)

    # (line0, col, name) comprehension loop-target positions mis-recorded here; skip on insertion.
    comprehension_target_positions: set[tuple[int, int, str]] = field(default_factory=set)

    # For function scopes
    parameters: dict[str, TypeInfo] = field(default_factory=dict)
    return_type: TypeInfo | None = None

    # For class scopes
    attributes: dict[str, TypeInfo] = field(default_factory=dict)

    def get_qualified_name(self) -> str:
        """Get dot-separated qualified name from module root, e.g. 'module.ClassName.method'."""
        if self.parent is None or self.parent.scope_type == ScopeType.MODULE:
            return self.name
        return f"{self.parent.get_qualified_name()}.{self.name}"

    def add_variable(self, var_name: str, type_info: TypeInfo) -> None:
        """Record a variable assignment in this scope's flow-sensitive history."""
        if var_name not in self.variable_history:
            self.variable_history[var_name] = []
        self.variable_history[var_name].append(type_info)

    def add_parameter(self, param_name: str, type_info: TypeInfo) -> None:
        """Add a parameter to this function scope."""
        self.parameters[param_name] = type_info

    @property
    def variables(self) -> dict[str, TypeInfo]:
        """Dict mapping each variable to its current (most recent) assignment's TypeInfo."""
        return {
            name: types[-1]
            for name, types in self.variable_history.items()
            if types  # Only include variables with at least one assignment
        }

    def get_variable_type_at_line(self, var_name: str, line: int) -> TypeInfo | None:
        """Flow-sensitive var type: most recent assignment at/before the line, else parent."""
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

        # Highest line wins; later passes append refinements out of order, so `[-1]` can be stale.
        # `>=` keeps the last-appended entry when several share that line (a refinement of an
        # earlier, weaker guess for the same binding).
        best = candidates[0]
        for type_info in candidates:
            if type_info.line >= best.line:
                best = type_info
        return best


@dataclass
class ScopeTree:
    """Tree of all module scopes: root scope plus a scope_id->Scope lookup map."""

    root: Scope
    scopes_by_id: dict[str, Scope] = field(default_factory=dict)

    # Lazily-built, invalidated-on-add caches; excluded from dataclass eq/repr (pure derived state).
    _line_index: list[Scope] | None = field(default=None, compare=False, repr=False)
    _function_scopes: list[Scope] | None = field(default=None, compare=False, repr=False)

    def add_scope(self, scope: Scope) -> None:
        """Register a scope in the tree and invalidate derived caches."""
        self.scopes_by_id[scope.scope_id] = scope
        self._line_index = None
        self._function_scopes = None

    def get_all_function_scopes(self) -> list[Scope]:
        """Get all FUNCTION scopes in the tree (cached)."""
        if self._function_scopes is None:
            self._function_scopes = [
                scope
                for scope in self.scopes_by_id.values()
                if scope.scope_type == ScopeType.FUNCTION
            ]
        return self._function_scopes

    def _node_line_range(self, node: ast.AST) -> tuple[int, int] | None:
        """Return 0-based start/end line range for an AST node, if available."""
        if not isinstance(node, HasLineRange):
            return None
        start_line = node.lineno - 1
        end_line = node.end_lineno - 1 if node.end_lineno is not None else start_line
        return start_line, end_line

    def _build_line_index(self) -> list[Scope]:
        """Build per-line scope index: winner is max-start_line non-MODULE scope; ties→latest."""
        max_end = -1
        for scope in self.scopes_by_id.values():
            if scope.scope_type == ScopeType.MODULE:
                continue
            line_range = self._node_line_range(scope.ast_node)
            if line_range is None:
                continue
            _, end_line = line_range
            if end_line > max_end:
                max_end = end_line

        # No eligible scopes: every query falls through to root.
        idx: list[Scope] = [self.root] * (max_end + 1)

        for scope in self.scopes_by_id.values():
            if scope.scope_type == ScopeType.MODULE:
                continue
            line_range = self._node_line_range(scope.ast_node)
            if line_range is None:
                continue
            start_line, end_line = line_range

            for line in range(max(start_line, 0), end_line + 1):
                incumbent = idx[line]
                if incumbent is self.root:
                    idx[line] = scope
                    continue
                incumbent_range = self._node_line_range(incumbent.ast_node)
                incumbent_start = incumbent_range[0] if incumbent_range is not None else -1
                if incumbent_start <= start_line:
                    idx[line] = scope

        return idx

    def find_scope_for_line(self, line: int) -> Scope:
        """Find the innermost scope containing a 0-based line (defaults to root)."""
        if self._line_index is None:
            self._line_index = self._build_line_index()

        idx = self._line_index
        return idx[line] if 0 <= line < len(idx) else self.root

    def get_variable_type_at_line(self, var_name: str, line: int) -> TypeInfo | None:
        """Type of a variable at a line across all scopes: locates the scope, then queries it."""
        # Find the scope that contains this line
        scope = self.find_scope_for_line(line)

        # Query the variable type in that scope
        return scope.get_variable_type_at_line(var_name, line)

    def get_function_scope_by_qualified_name(self, qualified_name: str) -> Scope | None:
        """Find a function scope by (possibly qualified) name, e.g. 'func', 'MyClass.method'."""
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
