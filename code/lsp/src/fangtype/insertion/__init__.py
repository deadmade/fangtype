"""Strategy-based type annotation insertion engine, consistent across single and bulk ops."""

from .engine import InsertionEngine
from .target_factory import (
    AssignmentTarget,
    SourceIndex,
    build_source_index,
    create_variable_target,
    detect_assignment_pattern,
    detect_assignment_pattern_indexed,
    find_assignment_target,
    find_assignment_target_indexed,
    find_function_line,
    find_function_line_indexed,
    find_variable_line,
)
from .types import (
    CodeLocation,
    InsertionContext,
    InsertionPlan,
    InsertionResult,
    InsertionTarget,
    TargetType,
    TransformationType,
)

__all__ = [
    "AssignmentTarget",
    "CodeLocation",
    "InsertionContext",
    "InsertionEngine",
    "InsertionPlan",
    "InsertionResult",
    "InsertionTarget",
    "SourceIndex",
    "TargetType",
    "TransformationType",
    "build_source_index",
    "create_variable_target",
    "detect_assignment_pattern",
    "detect_assignment_pattern_indexed",
    "find_assignment_target",
    "find_assignment_target_indexed",
    "find_function_line",
    "find_function_line_indexed",
    "find_variable_line",
]
