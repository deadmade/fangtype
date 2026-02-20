"""Type definitions for the Jedi-based type inference engine.

This module contains data classes and type definitions used throughout
the inference engine.
"""

import ast
from dataclasses import dataclass, field


@dataclass
class TypeInfo:
    """Type information for a variable or parameter.

    Attributes:
        type_str: The type as a string (e.g., "int", "str | None")
        source: Source of the type information (annotation, inference, etc.)
        line: Line number in source (0-based)
        col: Column number in source (0-based)
        ast_node: Optional AST node reference
    """

    type_str: str
    source: str = "inferred"
    line: int = 0
    col: int = 0
    ast_node: ast.AST | None = None


@dataclass
class TypeInferenceContext:
    """Context for type inference operations.

    Attributes:
        source: Python source code being analyzed
        path: Optional file path for project-aware inference
        project_root: Optional explicit project root path
        module_name: Optional module name for imports
        imports: Dictionary of imported names to their modules
    """

    source: str
    path: str | None = None
    project_root: str | None = None
    module_name: str | None = None
    imports: dict[str, str] = field(default_factory=dict)
