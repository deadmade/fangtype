"""Protocol and base classes for insertion strategies.

This module defines the InsertionStrategy protocol that all concrete
strategies must implement, along with utilities for strategy management.
"""

import logging
from abc import abstractmethod
from typing import Protocol, cast

import libcst as cst

from auto_type.inference.type_utils import sanitize_inferred_type

from .types import (
    InsertionContext,
    InsertionPlan,
    InsertionPlanMetadata,
    InsertionTarget,
    TransformationType,
)

logger = logging.getLogger(__name__)


class InsertionStrategy(Protocol):
    """Protocol that all insertion strategies must implement."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name for this strategy."""
        ...

    @abstractmethod
    def can_handle(self, target: InsertionTarget) -> bool:
        """Check if this strategy can handle the given insertion target.

        Args:
            target: The insertion target to check

        Returns:
            True if this strategy can handle the target, False otherwise
        """
        ...

    @abstractmethod
    def plan_insertion(self, target: InsertionTarget, context: InsertionContext) -> InsertionPlan:
        """Create an execution plan for the insertion without modifying code.

        Args:
            target: The insertion target to plan for
            context: Current insertion context with source and metadata

        Returns:
            InsertionPlan describing how to execute the insertion

        Raises:
            ValueError: If the target cannot be handled by this strategy
        """
        ...

    @abstractmethod
    def validate_type_syntax(self, type_str: str) -> bool:
        """Validate that a type annotation string has valid syntax.

        Args:
            type_str: The type annotation string to validate

        Returns:
            True if syntax is valid, False otherwise
        """
        ...


class BaseInsertionStrategy:
    """Base class providing common functionality for insertion strategies."""

    def __init__(self, name: str) -> None:
        """Initialize the strategy with a unique name.

        Args:
            name: Unique identifier for this strategy
        """
        self._name = name
        self._logger = logging.getLogger(f"{__name__}.{name}")

    @property
    def name(self) -> str:
        """Get the strategy name."""
        return self._name

    def validate_type_syntax(self, type_str: str) -> bool:
        """Validate type annotation syntax using LibCST.

        Args:
            type_str: Type annotation string to validate

        Returns:
            True if syntax is valid, False otherwise
        """
        try:
            cst.parse_expression(type_str.strip())
            return True
        except cst.ParserSyntaxError as e:
            self._logger.debug(f"Invalid type syntax '{type_str}': {e}")
            return False
        except Exception as e:
            self._logger.warning(f"Unexpected error validating type '{type_str}': {e}")
            return False

    def sanitize_type_annotation(self, type_str: str) -> str:
        """Sanitize and validate type annotation syntax.

        Args:
            type_str: Type annotation string to sanitize and validate

        Returns:
            A syntactically valid type annotation string

        Raises:
            ValueError: If no valid syntax can be produced
        """
        raw_type = type_str.strip()
        if self.validate_type_syntax(raw_type):
            return raw_type

        sanitized = sanitize_inferred_type(raw_type).strip()
        if sanitized != raw_type and self.validate_type_syntax(sanitized):
            self._logger.debug("Sanitized invalid type '%s' -> '%s'", raw_type, sanitized)
            return sanitized

        raise ValueError(f"Invalid type annotation syntax: {type_str}")

    def _create_plan(
        self,
        target: InsertionTarget,
        transformation: str,
        dependencies: list[str] | None = None,
        **metadata: object,
    ) -> InsertionPlan:
        """Create an insertion plan with common fields filled.

        Args:
            target: The insertion target
            transformation: Type of transformation to perform
            dependencies: Optional list of dependencies
            **metadata: Additional strategy-specific metadata

        Returns:
            InsertionPlan for this target
        """
        try:
            transformation_type = TransformationType(transformation)
        except ValueError as e:
            raise ValueError(f"Unknown transformation type: {transformation}") from e

        return InsertionPlan(
            strategy_name=self.name,
            target=target,
            transformation=transformation_type,
            dependencies=dependencies or [],
            metadata=cast(InsertionPlanMetadata, dict(metadata)),
        )

    def _log_planning(self, target: InsertionTarget, plan: InsertionPlan) -> None:
        """Log planning information for debugging.

        Args:
            target: The insertion target being planned
            plan: The resulting insertion plan
        """
        self._logger.debug(
            f"Planning {target.target_type.value} insertion for '{target.name}' "
            f"at line {target.location.line}: {plan.transformation.value}"
        )


def find_strategy_for_target(
    strategies: list[InsertionStrategy], target: InsertionTarget
) -> InsertionStrategy | None:
    """Find the first strategy that can handle the given target.

    Args:
        strategies: List of available strategies
        target: Target to find a strategy for

    Returns:
        First strategy that can handle the target, or None if none found
    """
    for strategy in strategies:
        try:
            if strategy.can_handle(target):
                return strategy
        except Exception as e:
            logger.warning(f"Error checking strategy {strategy.name} for target: {e}")

    return None


def validate_strategies(strategies: list[InsertionStrategy]) -> None:
    """Validate that strategies have unique names and are properly configured.

    Args:
        strategies: List of strategies to validate

    Raises:
        ValueError: If strategies are invalid or have duplicate names
    """
    if not strategies:
        raise ValueError("At least one strategy must be provided")

    names = [strategy.name for strategy in strategies]
    if len(names) != len(set(names)):
        duplicates = [name for name in names if names.count(name) > 1]
        raise ValueError(f"Duplicate strategy names found: {duplicates}")

    logger.info(f"Validated {len(strategies)} insertion strategies: {names}")
