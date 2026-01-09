"""Scope analyzer for building scope trees from Python source code.

This module provides the ScopeAnalyzer class which walks the AST and builds
a complete scope tree tracking all variables, parameters, and nested scopes.
"""

import ast
import logging

from auto_type.analysis.types import Scope, ScopeTree, ScopeType, TypeInfo, TypeSource

logger = logging.getLogger(__name__)


class ScopeAnalyzer(ast.NodeVisitor):
    """Builds a scope tree from Python source code.

    Uses the visitor pattern to walk the AST and track scope boundaries.
    Maintains a stack of current scopes to handle nesting correctly.

    Example:
        analyzer = ScopeAnalyzer()
        scope_tree = analyzer.analyze(source_code)
        # Access scopes
        module_scope = scope_tree.root
        func_scope = scope_tree.get_scope("func:my_function")
    """

    def __init__(self) -> None:
        """Initialize the scope analyzer."""
        self.scope_stack: list[Scope] = []
        self.scope_tree: ScopeTree | None = None
        self.scope_counter: dict[str, int] = {}  # For unique IDs

    def analyze(self, source: str) -> ScopeTree:
        """Analyze Python source code and build a scope tree.

        Args:
            source: Python source code as a string

        Returns:
            ScopeTree with all scopes and variables identified

        Raises:
            SyntaxError: If the source code has syntax errors
        """
        # Reset state for new analysis
        self.scope_stack = []
        self.scope_tree = None
        self.scope_counter = {}

        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            logger.error(f"Syntax error in source: {e}")
            raise

        # Create module-level scope
        module_scope = Scope(
            scope_id="module",
            scope_type=ScopeType.MODULE,
            name="<module>",
            ast_node=tree,
        )

        self.scope_tree = ScopeTree(root=module_scope)
        self.scope_tree.add_scope(module_scope)
        self.scope_stack.append(module_scope)

        # Visit all nodes
        self.visit(tree)

        return self.scope_tree

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Handle function definitions.

        Creates a new function scope and processes parameters and body.

        Args:
            node: FunctionDef AST node
        """
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Handle async function definitions.

        Args:
            node: AsyncFunctionDef AST node
        """
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Common handler for function and async function definitions.

        Args:
            node: FunctionDef or AsyncFunctionDef AST node
        """
        # Create new function scope
        parent_scope = self._current_scope()
        base_id = f"func:{node.name}"
        scope_id = self._generate_nested_scope_id(parent_scope, base_id)
        func_scope = Scope(
            scope_id=scope_id,
            scope_type=ScopeType.FUNCTION,
            name=node.name,
            ast_node=node,
            parent=parent_scope,
        )

        # Add parameters
        for arg in node.args.args:
            func_scope.add_parameter(
                arg.arg,
                TypeInfo(
                    type_str="Unknown",
                    source=TypeSource.UNKNOWN,
                    line=arg.lineno - 1,
                    col=arg.col_offset,
                    ast_node=arg,
                ),
            )

        # Handle *args
        if node.args.vararg:
            func_scope.add_parameter(
                node.args.vararg.arg,
                TypeInfo(
                    type_str="Unknown",
                    source=TypeSource.UNKNOWN,
                    line=node.args.vararg.lineno - 1,
                    col=node.args.vararg.col_offset,
                    ast_node=node.args.vararg,
                ),
            )

        # Handle **kwargs
        if node.args.kwarg:
            func_scope.add_parameter(
                node.args.kwarg.arg,
                TypeInfo(
                    type_str="Unknown",
                    source=TypeSource.UNKNOWN,
                    line=node.args.kwarg.lineno - 1,
                    col=node.args.kwarg.col_offset,
                    ast_node=node.args.kwarg,
                ),
            )

        # Register scope
        self._current_scope().children.append(func_scope)
        assert self.scope_tree is not None
        self.scope_tree.add_scope(func_scope)

        # Visit function body in new scope
        self.scope_stack.append(func_scope)
        for stmt in node.body:
            self.visit(stmt)
        self.scope_stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Handle class definitions.

        Creates a new class scope and processes methods and attributes.

        Args:
            node: ClassDef AST node
        """
        # Create new class scope
        parent_scope = self._current_scope()
        base_id = f"class:{node.name}"
        scope_id = self._generate_nested_scope_id(parent_scope, base_id)
        class_scope = Scope(
            scope_id=scope_id,
            scope_type=ScopeType.CLASS,
            name=node.name,
            ast_node=node,
            parent=parent_scope,
        )

        # Register scope
        self._current_scope().children.append(class_scope)
        assert self.scope_tree is not None
        self.scope_tree.add_scope(class_scope)

        # Visit class body in new scope
        self.scope_stack.append(class_scope)
        for stmt in node.body:
            self.visit(stmt)
        self.scope_stack.pop()

    def visit_Lambda(self, node: ast.Lambda) -> None:
        """Handle lambda expressions.

        Creates a lambda scope for the expression.

        Args:
            node: Lambda AST node
        """
        # Create new lambda scope
        parent_scope = self._current_scope()
        scope_id = self._generate_nested_scope_id(parent_scope, "lambda")
        lambda_scope = Scope(
            scope_id=scope_id,
            scope_type=ScopeType.LAMBDA,
            name="<lambda>",
            ast_node=node,
            parent=parent_scope,
        )

        # Add parameters
        for arg in node.args.args:
            lambda_scope.add_parameter(
                arg.arg,
                TypeInfo(
                    type_str="Unknown",
                    source=TypeSource.UNKNOWN,
                    line=arg.lineno - 1 if hasattr(arg, "lineno") else 0,
                    col=arg.col_offset if hasattr(arg, "col_offset") else 0,
                    ast_node=arg,
                ),
            )

        # Register scope
        self._current_scope().children.append(lambda_scope)
        assert self.scope_tree is not None
        self.scope_tree.add_scope(lambda_scope)

        # Visit lambda body in new scope
        self.scope_stack.append(lambda_scope)
        self.visit(node.body)
        self.scope_stack.pop()

    def visit_ListComp(self, node: ast.ListComp) -> None:
        """Handle list comprehensions.

        Creates a comprehension scope.

        Args:
            node: ListComp AST node
        """
        self._visit_comprehension(node, "listcomp")

    def visit_DictComp(self, node: ast.DictComp) -> None:
        """Handle dict comprehensions.

        Args:
            node: DictComp AST node
        """
        self._visit_comprehension(node, "dictcomp")

    def visit_SetComp(self, node: ast.SetComp) -> None:
        """Handle set comprehensions.

        Args:
            node: SetComp AST node
        """
        self._visit_comprehension(node, "setcomp")

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        """Handle generator expressions.

        Args:
            node: GeneratorExp AST node
        """
        self._visit_comprehension(node, "genexp")

    def _visit_comprehension(
        self,
        node: ast.ListComp | ast.DictComp | ast.SetComp | ast.GeneratorExp,
        comp_type: str,
    ) -> None:
        """Common handler for comprehension expressions.

        Args:
            node: Comprehension AST node
            comp_type: Type string for scope name
        """
        # Create comprehension scope
        parent_scope = self._current_scope()
        scope_id = self._generate_nested_scope_id(parent_scope, comp_type)
        comp_scope = Scope(
            scope_id=scope_id,
            scope_type=ScopeType.COMPREHENSION,
            name=f"<{comp_type}>",
            ast_node=node,
            parent=self._current_scope(),
        )

        # Register scope
        self._current_scope().children.append(comp_scope)
        assert self.scope_tree is not None
        self.scope_tree.add_scope(comp_scope)

        # Visit comprehension in new scope
        self.scope_stack.append(comp_scope)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_Assign(self, node: ast.Assign) -> None:
        """Handle variable assignments.

        Tracks simple assignments (x = value) in the current scope.

        Args:
            node: Assign AST node
        """
        # Only handle simple assignments: x = value
        if len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                var_name = target.id

                # Add to current scope's variables
                self._current_scope().add_variable(
                    var_name,
                    TypeInfo(
                        type_str="Unknown",  # Will be inferred later
                        source=TypeSource.UNKNOWN,
                        line=node.lineno - 1,
                        col=target.col_offset,
                        ast_node=node,
                    ),
                )
            elif isinstance(target, ast.Attribute):
                # Handle self.x = value for class attributes
                if (
                    isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                    and self._current_scope().scope_type == ScopeType.FUNCTION
                ):
                    # This is a class attribute assignment
                    # Look for the parent class scope
                    parent = self._current_scope().parent
                    if parent and parent.scope_type == ScopeType.CLASS:
                        parent.attributes[target.attr] = TypeInfo(
                            type_str="Unknown",
                            source=TypeSource.UNKNOWN,
                            line=node.lineno - 1,
                            col=target.col_offset,
                            ast_node=node,
                        )

        # Continue visiting child nodes
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """Handle annotated assignments.

        Tracks annotated assignments (x: int = value) but marks them as
        already having type information.

        Args:
            node: AnnAssign AST node
        """
        if isinstance(node.target, ast.Name):
            var_name = node.target.id

            # Extract the annotation string
            try:
                annotation_str = ast.unparse(node.annotation)
            except Exception:
                annotation_str = "Unknown"

            # Add to current scope with the annotation
            self._current_scope().add_variable(
                var_name,
                TypeInfo(
                    type_str=annotation_str,
                    source=TypeSource.LITERAL,  # Already annotated
                    line=node.lineno - 1,
                    col=node.target.col_offset,
                    ast_node=node,
                ),
            )
        elif isinstance(node.target, ast.Attribute):
            # Handle self.x: int = value for class attributes
            if (
                isinstance(node.target.value, ast.Name)
                and node.target.value.id == "self"
                and self._current_scope().scope_type == ScopeType.FUNCTION
            ):
                parent = self._current_scope().parent
                if parent and parent.scope_type == ScopeType.CLASS:
                    try:
                        annotation_str = ast.unparse(node.annotation)
                    except Exception:
                        annotation_str = "Unknown"

                    parent.attributes[node.target.attr] = TypeInfo(
                        type_str=annotation_str,
                        source=TypeSource.LITERAL,
                        line=node.lineno - 1,
                        col=node.target.col_offset,
                        ast_node=node,
                    )

        # Continue visiting child nodes
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        """Handle augmented assignments (x += 1).

        Args:
            node: AugAssign AST node
        """
        # For augmented assignments, the variable should already exist
        # We don't create a new entry, but continue visiting
        self.generic_visit(node)

    def _current_scope(self) -> Scope:
        """Get the current scope from the stack.

        Returns:
            The current (most nested) scope

        Raises:
            IndexError: If scope stack is empty (should never happen)
        """
        return self.scope_stack[-1]

    def _generate_nested_scope_id(self, parent_scope: Scope, base_id: str) -> str:
        """Generate a scope ID for a nested scope.

        For nested scopes, prepends the parent's scope ID.
        For module-level scopes, just uses the base ID.

        Args:
            parent_scope: The parent scope
            base_id: Base ID for this scope (e.g., "func:foo", "class:Bar")

        Returns:
            Full scope ID (e.g., "func:outer.inner", NOT "func:outer.func:inner")
        """
        if parent_scope.scope_type == ScopeType.MODULE:
            # Module-level scope, just use base ID
            return self._generate_scope_id(base_id)
        else:
            # Nested scope: extract name from base_id and append to parent
            # base_id is like "func:inner" or "class:Inner", we want just "inner"
            if ":" in base_id:
                _, name = base_id.split(":", 1)
            else:
                name = base_id

            nested_base = f"{parent_scope.scope_id}.{name}"
            return self._generate_scope_id(nested_base)

    def _generate_scope_id(self, base: str) -> str:
        """Generate a unique scope ID.

        If multiple scopes have the same base name, appends a counter.
        For example: "func:foo", "func:foo#1", "func:foo#2"

        Args:
            base: Base name for the scope ID

        Returns:
            Unique scope ID string
        """
        count = self.scope_counter.get(base, 0)
        self.scope_counter[base] = count + 1

        if count == 0:
            return base
        return f"{base}#{count}"
