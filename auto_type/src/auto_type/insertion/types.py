"""Core data structures for the unified insertion engine.

This module defines the fundamental data types used throughout the unified
insertion system, including targets, plans, and results.
"""

import ast
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TargetType(Enum):
    """Types of insertion targets supported by the unified engine."""

    VARIABLE_SIMPLE = "variable_simple"  # x = 42
    VARIABLE_COMPLEX = "variable_complex"  # a, b = 1, 2
    FUNCTION_PARAMETER = "function_parameter"  # def f(x): -> def f(x: int):
    FUNCTION_RETURN = "function_return"  # def f(): -> def f() -> int:
    CLASS_VARIABLE = "class_variable"  # Future: class-level annotations
    FUNCTION_SCOPE_VARIABLE = "function_scope_variable"  # Future: vars in functions

    @classmethod
    def from_string(cls, value: str) -> "TargetType":
        """Create TargetType from string value."""
        for target_type in cls:
            if target_type.value == value:
                return target_type
        raise ValueError(f"Unknown target type: {value}")


class TransformationType(Enum):
    """How the insertion should be performed at the LibCST level."""

    IN_PLACE = "in_place"  # Convert existing node (Assign -> AnnAssign)
    DECLARATION = "declaration"  # Insert standalone declaration before statement
    REPLACEMENT = "replacement"  # Replace existing annotation
    FUNCTION_SIGNATURE = "function_signature"  # Modify function signature


@dataclass
class CodeLocation:
    """Location in source code where insertion should occur."""

    line: int
    column: int
    end_line: int | None = None
    end_column: int | None = None
    scope_id: str | None = None  # For function/class scope tracking

    def __post_init__(self) -> None:
        """Validate location data."""
        if self.line < 1:
            raise ValueError(f"Line must be >= 1, got {self.line}")
        if self.column < 0:
            raise ValueError(f"Column must be >= 0, got {self.column}")


@dataclass
class InsertionTarget:
    """Describes what to insert and where."""

    target_type: TargetType
    location: CodeLocation
    type_annotation: str
    name: str  # Variable/parameter name
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate target data."""
        if not self.type_annotation.strip():
            raise ValueError("Type annotation cannot be empty")
        if not self.name.strip():
            raise ValueError("Name cannot be empty")

    @property
    def is_variable_target(self) -> bool:
        """Check if this is a variable-related insertion."""
        return self.target_type in (TargetType.VARIABLE_SIMPLE, TargetType.VARIABLE_COMPLEX)

    @property
    def is_function_target(self) -> bool:
        """Check if this is a function-related insertion."""
        return self.target_type in (TargetType.FUNCTION_PARAMETER, TargetType.FUNCTION_RETURN)


@dataclass
class InsertionPlan:
    """Execution plan for a single insertion."""

    strategy_name: str  # Name of the strategy that will handle this
    target: InsertionTarget
    transformation: TransformationType
    dependencies: list[str] = field(default_factory=list)  # Other target names this depends on
    metadata: dict[str, Any] = field(default_factory=dict)  # Strategy-specific data

    @property
    def priority(self) -> int:
        """Execution priority for dependency resolution."""
        # Higher priority = execute first
        priority_map = {
            TransformationType.DECLARATION: 100,  # Declarations must come before their usage
            TransformationType.IN_PLACE: 50,
            TransformationType.REPLACEMENT: 30,
            TransformationType.FUNCTION_SIGNATURE: 20,
        }
        return priority_map.get(self.transformation, 0)


@dataclass
class InsertionResult:
    """Result of an insertion operation."""

    modified_source: str
    success: bool
    inserted_count: int
    error_message: str | None = None
    failed_targets: list[InsertionTarget] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def has_changes(self) -> bool:
        """Check if any changes were made."""
        return self.inserted_count > 0

    @classmethod
    def success_result(
        cls,
        modified_source: str,
        inserted_count: int,
        details: dict[str, Any] | None = None,
    ) -> "InsertionResult":
        """Create a successful insertion result."""
        return cls(
            modified_source=modified_source,
            success=True,
            inserted_count=inserted_count,
            details=details or {},
        )

    @classmethod
    def error_result(
        cls,
        original_source: str,
        error_message: str,
        failed_targets: list[InsertionTarget] | None = None,
    ) -> "InsertionResult":
        """Create an error insertion result."""
        return cls(
            modified_source=original_source,
            success=False,
            inserted_count=0,
            error_message=error_message,
            failed_targets=failed_targets or [],
        )


@dataclass
class InsertionContext:
    """Context information available to insertion strategies."""

    source: str
    existing_annotations: dict[str, str] = field(default_factory=dict)  # name -> type_str
    scope_info: dict[str, Any] = field(default_factory=dict)
    ast_tree: ast.AST | None = None

    def has_annotation(self, name: str) -> bool:
        """Check if a variable already has an annotation."""
        return name in self.existing_annotations

    def get_annotation(self, name: str) -> str | None:
        """Get existing annotation for a variable."""
        return self.existing_annotations.get(name)
