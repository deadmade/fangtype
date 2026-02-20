"""Unified insertion engine package.

This package provides a clean, strategy-based approach to type annotation insertion
that eliminates code duplication and ensures consistency between single and bulk operations.
"""

from .engine import UnifiedInsertionEngine
from .strategies import create_default_strategies
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
    "InsertionPlan",
    "InsertionResult",
    "InsertionTarget",
    "SourceIndex",
    "TargetType",
    "TransformationType",
    "UnifiedInsertionEngine",
    "build_source_index",
    "create_default_strategies",
    "create_variable_target",
    "detect_assignment_pattern",
    "detect_assignment_pattern_indexed",
    "find_assignment_target",
    "find_assignment_target_indexed",
    "find_function_line",
    "find_function_line_indexed",
    "find_variable_line",
]
