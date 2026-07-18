"""Core data structures (targets, plans, results) for the unified insertion engine."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, TypedDict


class TargetType(Enum):
    """Types of insertion targets supported by the unified engine."""

    VARIABLE_SIMPLE = "variable_simple"  # x = 42
    VARIABLE_COMPLEX = "variable_complex"  # a, b = 1, 2
    FUNCTION_PARAMETER = "function_parameter"  # def f(x): -> def f(x: int):
    FUNCTION_RETURN = "function_return"  # def f(): -> def f() -> int:
    SUBSCRIPT_ACCESS = "subscript_access"  # value = d['key'] -> value: Type = d['key']
    ATTRIBUTE_ACCESS = "attribute_access"  # self.attr = value -> self.attr: Type = value
    ITERATION_VARIABLE = "iteration_variable"  # for i in range(10) -> i: Type (pre-declaration)


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

    def __post_init__(self) -> None:
        """Validate location data."""
        if self.line < 1:
            raise ValueError(f"Line must be >= 1, got {self.line}")
        if self.column < 0:
            raise ValueError(f"Column must be >= 0, got {self.column}")


class InsertionPlanMetadata(TypedDict, total=False):
    """Metadata used by insertion plans and transformer execution."""

    variable_name: str
    type_annotation: str
    new_type: str
    parameter_name: str
    annotation_kind: Literal["parameter", "return"]


def empty_plan_metadata() -> InsertionPlanMetadata:
    """Return an empty metadata mapping for plans."""
    return {}


@dataclass
class InsertionTarget:
    """Describes what to insert and where."""

    target_type: TargetType
    location: CodeLocation
    type_annotation: str
    name: str  # Variable/parameter name

    def __post_init__(self) -> None:
        """Validate target data."""
        if not self.type_annotation.strip():
            raise ValueError("Type annotation cannot be empty")
        if not self.name.strip():
            raise ValueError("Name cannot be empty")


@dataclass
class InsertionPlan:
    """Execution plan for a single insertion."""

    strategy_name: str  # Name of the strategy that will handle this
    target: InsertionTarget
    transformation: TransformationType
    metadata: InsertionPlanMetadata = field(default_factory=empty_plan_metadata)


@dataclass
class InsertionResult:
    """Result of an insertion operation."""

    modified_source: str
    success: bool
    inserted_count: int
    error_message: str | None = None
    failed_targets: list[InsertionTarget] = field(default_factory=list)
    details: dict[str, object] = field(default_factory=dict)

    @classmethod
    def success_result(
        cls,
        modified_source: str,
        inserted_count: int,
        details: dict[str, object] | None = None,
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
    # (name, line) -> type_str. Keyed by line so a same-named binding elsewhere in the file
    # is not mistaken for this one's annotation.
    existing_annotations: dict[tuple[str, int], str] = field(default_factory=dict)

    def has_annotation(self, name: str, line: int) -> bool:
        """Check if a variable already has an annotation on the given line."""
        return (name, line) in self.existing_annotations
