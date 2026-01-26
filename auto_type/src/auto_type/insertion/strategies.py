"""Concrete insertion strategies for different annotation types.

This module contains the actual strategy implementations that handle
specific types of type annotation insertions.
"""

import logging

from .strategy import BaseInsertionStrategy
from .types import InsertionContext, InsertionPlan, InsertionTarget, TargetType

logger = logging.getLogger(__name__)


class VariableAssignmentStrategy(BaseInsertionStrategy):
    """Strategy for simple variable assignments: x = 42 -> x: int = 42"""

    def __init__(self) -> None:
        super().__init__("variable_assignment")

    def can_handle(self, target: InsertionTarget) -> bool:
        """Check if this strategy can handle simple variable assignments."""
        return target.target_type == TargetType.VARIABLE_SIMPLE

    def plan_insertion(self, target: InsertionTarget, context: InsertionContext) -> InsertionPlan:
        """Plan insertion for simple variable assignment.

        This strategy converts: x = value  ->  x: type = value
        Uses LibCST's IN_PLACE transformation (Assign -> AnnAssign)
        """
        if not self.can_handle(target):
            raise ValueError(f"VariableAssignmentStrategy cannot handle {target.target_type}")

        if not self.validate_type_syntax(target.type_annotation):
            raise ValueError(f"Invalid type annotation syntax: {target.type_annotation}")

        # Check if variable already has annotation
        if context.has_annotation(target.name):
            existing_type = context.get_annotation(target.name)
            plan = self._create_plan(
                target,
                "replacement",
                existing_type=existing_type,
                new_type=target.type_annotation,
            )
        else:
            plan = self._create_plan(
                target,
                "in_place",
                variable_name=target.name,
                type_annotation=target.type_annotation,
            )

        self._log_planning(target, plan)
        return plan


class ComplexAssignmentStrategy(BaseInsertionStrategy):
    """Strategy for complex assignments that require standalone declarations.

    Handles:
    - Tuple unpacking: a, b = 1, 2
    - Chained assignments: a = b = 42
    - List unpacking: [a, b] = [1, 2]
    - Starred expressions: a, *b, c = [1, 2, 3, 4]
    """

    def __init__(self) -> None:
        super().__init__("complex_assignment")

    def can_handle(self, target: InsertionTarget) -> bool:
        """Check if this strategy handles complex variable assignments."""
        return target.target_type == TargetType.VARIABLE_COMPLEX

    def plan_insertion(self, target: InsertionTarget, context: InsertionContext) -> InsertionPlan:
        """Plan insertion for complex variable assignment.

        This strategy inserts standalone declarations before complex assignments:
        a, b = 1, 2  ->  a: int; b: int; a, b = 1, 2
        """
        if not self.can_handle(target):
            raise ValueError(f"ComplexAssignmentStrategy cannot handle {target.target_type}")

        if not self.validate_type_syntax(target.type_annotation):
            raise ValueError(f"Invalid type annotation syntax: {target.type_annotation}")

        # Check if variable already has annotation
        if context.has_annotation(target.name):
            existing_type = context.get_annotation(target.name)
            plan = self._create_plan(
                target,
                "replacement",
                existing_type=existing_type,
                new_type=target.type_annotation,
            )
        else:
            plan = self._create_plan(
                target,
                "declaration",
                variable_name=target.name,
                type_annotation=target.type_annotation,
            )

        self._log_planning(target, plan)
        return plan


class FunctionParameterStrategy(BaseInsertionStrategy):
    """Strategy for function parameter annotations: def f(x): -> def f(x: int):"""

    def __init__(self) -> None:
        super().__init__("function_parameter")

    def can_handle(self, target: InsertionTarget) -> bool:
        """Check if this strategy handles function parameter annotations."""
        return target.target_type == TargetType.FUNCTION_PARAMETER

    def plan_insertion(self, target: InsertionTarget, context: InsertionContext) -> InsertionPlan:
        """Plan insertion for function parameter annotation."""
        if not self.can_handle(target):
            raise ValueError(f"FunctionParameterStrategy cannot handle {target.target_type}")

        if not self.validate_type_syntax(target.type_annotation):
            raise ValueError(f"Invalid type annotation syntax: {target.type_annotation}")

        plan = self._create_plan(
            target,
            "function_signature",
            parameter_name=target.name,
            type_annotation=target.type_annotation,
            annotation_kind="parameter",
        )

        self._log_planning(target, plan)
        return plan


class FunctionReturnStrategy(BaseInsertionStrategy):
    """Strategy for function return type annotations: def f(): -> def f() -> int:"""

    def __init__(self) -> None:
        super().__init__("function_return")

    def can_handle(self, target: InsertionTarget) -> bool:
        """Check if this strategy handles function return type annotations."""
        return target.target_type == TargetType.FUNCTION_RETURN

    def plan_insertion(self, target: InsertionTarget, context: InsertionContext) -> InsertionPlan:
        """Plan insertion for function return type annotation."""
        if not self.can_handle(target):
            raise ValueError(f"FunctionReturnStrategy cannot handle {target.target_type}")

        if not self.validate_type_syntax(target.type_annotation):
            raise ValueError(f"Invalid type annotation syntax: {target.type_annotation}")

        plan = self._create_plan(
            target,
            "function_signature",
            function_name=target.name,
            type_annotation=target.type_annotation,
            annotation_kind="return",
        )

        self._log_planning(target, plan)
        return plan


class ClassVariableStrategy(BaseInsertionStrategy):
    """Strategy for class-level variable annotations (future extension)."""

    def __init__(self) -> None:
        super().__init__("class_variable")

    def can_handle(self, target: InsertionTarget) -> bool:
        """Check if this strategy handles class variable annotations."""
        return target.target_type == TargetType.CLASS_VARIABLE

    def plan_insertion(self, target: InsertionTarget, context: InsertionContext) -> InsertionPlan:
        """Plan insertion for class variable annotation."""
        if not self.can_handle(target):
            raise ValueError(f"ClassVariableStrategy cannot handle {target.target_type}")

        if not self.validate_type_syntax(target.type_annotation):
            raise ValueError(f"Invalid type annotation syntax: {target.type_annotation}")

        # For now, use in_place transformation - this will need refinement
        plan = self._create_plan(
            target,
            "in_place",
            variable_name=target.name,
            type_annotation=target.type_annotation,
            scope="class",
        )

        self._log_planning(target, plan)
        return plan


class FunctionScopeVariableStrategy(BaseInsertionStrategy):
    """Strategy for variables inside function bodies (future extension)."""

    def __init__(self) -> None:
        super().__init__("function_scope_variable")

    def can_handle(self, target: InsertionTarget) -> bool:
        """Check if this strategy handles function-scoped variable annotations."""
        return target.target_type == TargetType.FUNCTION_SCOPE_VARIABLE

    def plan_insertion(self, target: InsertionTarget, context: InsertionContext) -> InsertionPlan:
        """Plan insertion for function-scoped variable annotation."""
        if not self.can_handle(target):
            raise ValueError(f"FunctionScopeVariableStrategy cannot handle {target.target_type}")

        if not self.validate_type_syntax(target.type_annotation):
            raise ValueError(f"Invalid type annotation syntax: {target.type_annotation}")

        # Use in_place for simple assignments, declaration for complex ones
        # This determination could be made more sophisticated
        transformation = "in_place" if "," not in target.name else "declaration"

        plan = self._create_plan(
            target,
            transformation,
            variable_name=target.name,
            type_annotation=target.type_annotation,
            scope="function",
            scope_id=target.location.scope_id,
        )

        self._log_planning(target, plan)
        return plan


def create_default_strategies() -> list[BaseInsertionStrategy]:
    """Create the default set of insertion strategies.

    Returns:
        List of strategy instances ready for use
    """
    return [
        VariableAssignmentStrategy(),
        ComplexAssignmentStrategy(),
        FunctionParameterStrategy(),
        FunctionReturnStrategy(),
        ClassVariableStrategy(),
        FunctionScopeVariableStrategy(),
    ]
