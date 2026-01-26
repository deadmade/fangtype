"""Unified insertion engine package.

This package provides a clean, strategy-based approach to type annotation insertion
that eliminates code duplication and ensures consistency between single and bulk operations.
"""

from .engine import UnifiedInsertionEngine
from .strategies import create_default_strategies
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
    "CodeLocation",
    "InsertionContext",
    "InsertionPlan",
    "InsertionResult",
    "InsertionTarget",
    "TargetType",
    "TransformationType",
    "UnifiedInsertionEngine",
    "create_default_strategies",
]
