"""Literal type inference engine for simple Python expressions."""

import ast


class LiteralInferenceEngine:
    """Infers types from literal expressions in Python code.

    This engine handles only simple cases:
    - Integer literals: x = 42 → int
    - String literals: x = "hello" → str
    - Boolean literals: x = True → bool
    - List literals: x = [] → list
    - Dict literals: x = {} → dict
    - Set literals: x = {1, 2} → set
    - Tuple literals: x = (1, 2) → tuple
    - None literals: x = None → None
    """

    def infer_from_node(self, node: ast.expr) -> str | None:
        """Infer type from an AST expression node.

        Args:
            node: An AST expression node to analyze

        Returns:
            Type string (e.g., "int", "str") or None if type cannot be inferred
        """
        match node:
            case ast.Constant(value=bool()):
                # Must check bool before int since bool is subclass of int
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
            case ast.List():
                return "list"
            case ast.Dict():
                return "dict"
            case ast.Set():
                return "set"
            case ast.Tuple():
                return "tuple"
            case ast.ListComp():
                return "list"
            case ast.DictComp():
                return "dict"
            case ast.SetComp():
                return "set"
            case _:
                return None

    def infer_variable_types(self, source: str) -> dict[str, str]:
        """Infer types for all simple variable assignments in source code.

        Args:
            source: Python source code as string

        Returns:
            Dictionary mapping variable names to inferred type strings
        """
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return {}

        types: dict[str, str] = {}

        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                # Only handle simple single-target assignments
                if len(node.targets) == 1:
                    target = node.targets[0]
                    if isinstance(target, ast.Name):
                        inferred_type = self.infer_from_node(node.value)
                        if inferred_type:
                            types[target.id] = inferred_type

            elif isinstance(node, ast.AnnAssign):
                # Already annotated, skip
                continue

        return types

    def get_variable_positions(self, source: str) -> dict[str, tuple[int, int]]:
        """Get line and column positions for variables that can be typed.

        Args:
            source: Python source code as string

        Returns:
            Dictionary mapping variable names to (line, column) tuples
        """
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return {}

        positions: dict[str, tuple[int, int]] = {}

        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name):
                    inferred_type = self.infer_from_node(node.value)
                    if inferred_type:
                        # Store 0-indexed line and column
                        positions[target.id] = (node.lineno - 1, target.col_offset)

        return positions
