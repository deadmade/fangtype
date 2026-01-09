"""Lightweight type validator for checking type string validity."""

import ast
import keyword


class TypeValidator:
    """Fast validator for type strings before displaying as ghost text.

    This validator performs lightweight checks:
    1. Type exists in Python builtins (int, str, list, etc.)
    2. Type exists in typing module (List, Dict, Optional, etc.)
    3. Type is imported or defined in the current file scope
    4. Type syntax is valid (valid Python identifier)

    It does NOT perform deep semantic analysis like Mypy/Pyright.
    The goal is to prevent obviously wrong types while staying fast (<10ms).
    """

    def __init__(self) -> None:
        """Initialize the validator with known type names."""
        # Python built-in types
        self.builtins: set[str] = {
            "int",
            "str",
            "float",
            "bool",
            "bytes",
            "list",
            "dict",
            "set",
            "tuple",
            "frozenset",
            "object",
            "type",
            "None",
            "complex",
            "bytearray",
            "memoryview",
            "range",
        }

        # Common typing module types
        self.typing_types: set[str] = {
            "List",
            "Dict",
            "Set",
            "Tuple",
            "FrozenSet",
            "Optional",
            "Union",
            "Any",
            "Callable",
            "Sequence",
            "Iterable",
            "Iterator",
            "Mapping",
            "MutableMapping",
            "TypeVar",
            "Generic",
            "Protocol",
            "Literal",
            "Final",
            "ClassVar",
            "TypedDict",
            "Annotated",
        }

    def is_valid_identifier(self, type_str: str) -> bool:
        """Check if type string is a valid Python identifier.

        Args:
            type_str: Type string to validate

        Returns:
            True if valid identifier, False otherwise
        """
        # Basic syntax check
        if not type_str:
            return False

        # Special case: None is a keyword but valid type
        if type_str == "None":
            return True

        # Check for other keywords
        if keyword.iskeyword(type_str):
            return False

        # Try to parse as expression (handles generics like list[int])
        try:
            ast.parse(type_str, mode="eval")
            return True
        except SyntaxError:
            return False

    def validate(self, type_str: str, scope: set[str] | None = None) -> bool:
        """Validate if a type string is likely valid.

        Args:
            type_str: Type string to validate (e.g., "int", "list", "MyClass")
            scope: Optional set of names available in current scope
                  (imported modules, defined classes, etc.)

        Returns:
            True if type appears valid, False otherwise
        """
        if not self.is_valid_identifier(type_str):
            return False

        # Extract base type name (for generics like list[int])
        base_type = type_str.split("[")[0].strip()

        # Check builtins
        if base_type in self.builtins:
            return True

        # Check typing module
        if base_type in self.typing_types:
            return True

        # Check provided scope
        if scope and base_type in scope:
            return True

        # Unknown type - could be from external module
        # For now, reject to be safe
        return False

    def extract_scope_names(self, source: str) -> set[str]:
        """Extract available type names from source code.

        This includes:
        - Imported module names
        - Imported type names (from typing import List)
        - Class definitions
        - Type aliases

        Args:
            source: Python source code as string

        Returns:
            Set of names that are valid types in this scope
        """
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return set()

        names: set[str] = set()

        for node in ast.walk(tree):
            # Import statements: import foo
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname if alias.asname else alias.name
                    names.add(name)

            # From imports: from typing import List
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    name = alias.asname if alias.asname else alias.name
                    names.add(name)

            # Class definitions
            elif isinstance(node, ast.ClassDef):
                names.add(node.name)

            # Type aliases: MyType = int
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        # Heuristic: uppercase name likely a type alias
                        if target.id[0].isupper():
                            names.add(target.id)

        return names
