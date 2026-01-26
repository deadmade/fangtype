"""Unified LibCST transformer that executes all insertion plans.

This module contains the UnifiedTransformer class that performs all
type annotation insertions in a single pass through the LibCST tree.
"""

import logging
from collections import defaultdict

import libcst as cst
from libcst.metadata import PositionProvider

from .types import InsertionPlan, TargetType, TransformationType

logger = logging.getLogger(__name__)


class UnifiedTransformer(cst.CSTTransformer):
    """Single transformer that executes all planned insertions uniformly."""

    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, plans: list[InsertionPlan]) -> None:
        """Initialize transformer with execution plans.

        Args:
            plans: List of insertion plans to execute, sorted by priority
        """
        self._plans = plans

        # Track execution results
        self.inserted_count = 0
        self.failed_insertions: list[InsertionPlan] = []
        self.execution_details: dict[str, list[str]] = defaultdict(list)

        self._logger = logging.getLogger(f"{__name__}.UnifiedTransformer")

    def leave_SimpleStatementLine(
        self, original_node: cst.SimpleStatementLine, updated_node: cst.SimpleStatementLine
    ) -> cst.SimpleStatementLine | cst.FlattenSentinel[cst.SimpleStatementLine]:
        """Handle all line-based insertions uniformly."""
        # For now, process all plans by checking node content rather than line numbers
        # This is a simplified approach that doesn't require metadata

        # Find plans that match this statement
        matching_plans = []
        for plan in self._plans:
            if plan.transformation in (
                TransformationType.IN_PLACE,
                TransformationType.REPLACEMENT,
                TransformationType.DECLARATION,
            ):
                # Check if this statement contains the target variable
                if self._statement_contains_variable(updated_node, plan.target.name):
                    matching_plans.append(plan)

        if not matching_plans:
            return updated_node

        self._logger.debug(f"Processing {len(matching_plans)} plans for statement")

        # Group plans by transformation type
        in_place_plans = [
            p for p in matching_plans if p.transformation == TransformationType.IN_PLACE
        ]
        replacement_plans = [
            p for p in matching_plans if p.transformation == TransformationType.REPLACEMENT
        ]
        declaration_plans = [
            p for p in matching_plans if p.transformation == TransformationType.DECLARATION
        ]

        # Process in-place and replacement transformations
        modified_node = updated_node
        for plan in in_place_plans + replacement_plans:
            try:
                modified_node = self._apply_variable_plan(modified_node, plan)
                self.inserted_count += 1
                self.execution_details[plan.strategy_name].append(f"{plan.target.name}")
            except Exception as e:
                self._logger.warning(f"Failed to apply plan for {plan.target.name}: {e}")
                self.failed_insertions.append(plan)

        # Handle declarations - these need to be inserted before the line
        if declaration_plans:
            declaration_statements = []
            for plan in declaration_plans:
                try:
                    declaration_stmt = self._create_declaration_statement(plan)
                    declaration_statements.append(declaration_stmt)
                    self.inserted_count += 1
                    self.execution_details[plan.strategy_name].append(
                        f"{plan.target.name} (declaration)"
                    )
                except Exception as e:
                    self._logger.warning(
                        f"Failed to create declaration for {plan.target.name}: {e}"
                    )
                    self.failed_insertions.append(plan)

            if declaration_statements:
                # Return flattened sequence: declarations + original statement
                return cst.FlattenSentinel(declaration_statements + [modified_node])

        return modified_node

    def _statement_contains_variable(
        self, node: cst.SimpleStatementLine, variable_name: str
    ) -> bool:
        """Check if a statement contains an assignment to the given variable."""
        for stmt in node.body:
            if isinstance(stmt, cst.Assign):
                # Check simple assignments: x = value
                for target in stmt.targets:
                    if isinstance(target.target, cst.Name) and target.target.value == variable_name:
                        return True
                    # Check complex assignments: a, b = 1, 2
                    if isinstance(target.target, cst.Tuple | cst.List):
                        for element in target.target.elements:
                            if isinstance(element, cst.Element) and isinstance(
                                element.value, cst.Name
                            ):
                                if element.value.value == variable_name:
                                    return True
            elif isinstance(stmt, cst.AnnAssign):
                # Check annotated assignments: x: type = value
                if isinstance(stmt.target, cst.Name) and stmt.target.value == variable_name:
                    return True
        return False

    def leave_FunctionDef(
        self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef
    ) -> cst.FunctionDef:
        """Handle function signature insertions."""
        # Find plans that match this function
        function_name = original_node.name.value
        matching_plans = []

        for plan in self._plans:
            if plan.transformation == TransformationType.FUNCTION_SIGNATURE:
                if (
                    plan.target.target_type == TargetType.FUNCTION_RETURN
                    and plan.target.name == function_name
                ) or (
                    plan.target.target_type == TargetType.FUNCTION_PARAMETER
                    and plan.target.name
                    in [param.name.value for param in original_node.params.params]
                ):
                    matching_plans.append(plan)

        if not matching_plans:
            return updated_node

        self._logger.debug(f"Processing {len(matching_plans)} function plans for {function_name}")

        modified_node = updated_node
        for plan in matching_plans:
            try:
                modified_node = self._apply_function_plan(modified_node, plan)
                self.inserted_count += 1
                annotation_kind = plan.metadata.get("annotation_kind", "unknown")
                self.execution_details[plan.strategy_name].append(
                    f"{plan.target.name} ({annotation_kind})"
                )
            except Exception as e:
                self._logger.warning(f"Failed to apply function plan for {plan.target.name}: {e}")
                self.failed_insertions.append(plan)

        return modified_node

    def _apply_variable_plan(
        self, node: cst.SimpleStatementLine, plan: InsertionPlan
    ) -> cst.SimpleStatementLine:
        """Apply a variable annotation plan to a statement line."""
        if plan.transformation == TransformationType.IN_PLACE:
            return self._apply_in_place_transformation(node, plan)
        elif plan.transformation == TransformationType.REPLACEMENT:
            return self._apply_replacement_transformation(node, plan)
        else:
            raise ValueError(f"Unsupported transformation for variable: {plan.transformation}")

    def _apply_in_place_transformation(
        self, node: cst.SimpleStatementLine, plan: InsertionPlan
    ) -> cst.SimpleStatementLine:
        """Convert Assign to AnnAssign: x = value -> x: type = value"""
        variable_name = plan.target.name
        type_annotation = plan.metadata["type_annotation"]

        # Find the assignment statement for this variable
        for i, statement in enumerate(node.body):
            if isinstance(statement, cst.SimpleStatementSuite):
                continue  # Skip compound statements

            if isinstance(statement, cst.Assign):
                # Check if this assignment targets our variable
                for target in statement.targets:
                    if isinstance(target.target, cst.Name) and target.target.value == variable_name:
                        # Convert to annotated assignment
                        try:
                            type_expr = cst.parse_expression(type_annotation)
                            ann_assign = cst.AnnAssign(
                                target=target.target,
                                annotation=cst.Annotation(annotation=type_expr),
                                value=statement.value,
                                equal=cst.AssignEqual(
                                    whitespace_before=cst.SimpleWhitespace(" "),
                                    whitespace_after=cst.SimpleWhitespace(" "),
                                ),
                            )

                            # Replace the statement
                            new_body = list(node.body)
                            new_body[i] = ann_assign
                            return node.with_changes(body=new_body)

                        except cst.ParserSyntaxError as e:
                            raise ValueError(f"Invalid type annotation '{type_annotation}': {e}")

        # If we get here, we didn't find the assignment
        raise ValueError(f"Could not find assignment for variable '{variable_name}'")

    def _apply_replacement_transformation(
        self, node: cst.SimpleStatementLine, plan: InsertionPlan
    ) -> cst.SimpleStatementLine:
        """Replace existing annotation: x: old_type = value -> x: new_type = value"""
        variable_name = plan.target.name
        new_type = plan.metadata["new_type"]

        # Find the annotated assignment for this variable
        for i, statement in enumerate(node.body):
            if isinstance(statement, cst.AnnAssign):
                if (
                    isinstance(statement.target, cst.Name)
                    and statement.target.value == variable_name
                ):
                    try:
                        new_type_expr = cst.parse_expression(new_type)
                        new_annotation = cst.Annotation(annotation=new_type_expr)
                        new_ann_assign = statement.with_changes(annotation=new_annotation)

                        # Replace the statement
                        new_body = list(node.body)
                        new_body[i] = new_ann_assign
                        return node.with_changes(body=new_body)

                    except cst.ParserSyntaxError as e:
                        raise ValueError(f"Invalid type annotation '{new_type}': {e}")

        raise ValueError(f"Could not find existing annotation for variable '{variable_name}'")

    def _create_declaration_statement(self, plan: InsertionPlan) -> cst.SimpleStatementLine:
        """Create standalone declaration: var_name: type"""
        variable_name = plan.metadata["variable_name"]
        type_annotation = plan.metadata["type_annotation"]

        try:
            type_expr = cst.parse_expression(type_annotation)
            ann_assign = cst.AnnAssign(
                target=cst.Name(variable_name),
                annotation=cst.Annotation(annotation=type_expr),
                value=None,  # Declaration only, no value
            )

            return cst.SimpleStatementLine(body=[ann_assign])

        except cst.ParserSyntaxError as e:
            raise ValueError(f"Invalid type annotation '{type_annotation}': {e}")

    def _apply_function_plan(self, node: cst.FunctionDef, plan: InsertionPlan) -> cst.FunctionDef:
        """Apply function signature annotation plan."""
        annotation_kind = plan.metadata.get("annotation_kind")

        if annotation_kind == "parameter":
            return self._add_parameter_annotation(node, plan)
        elif annotation_kind == "return":
            return self._add_return_annotation(node, plan)
        else:
            raise ValueError(f"Unknown function annotation kind: {annotation_kind}")

    def _add_parameter_annotation(
        self, node: cst.FunctionDef, plan: InsertionPlan
    ) -> cst.FunctionDef:
        """Add type annotation to function parameter."""
        parameter_name = plan.metadata["parameter_name"]
        type_annotation = plan.metadata["type_annotation"]

        try:
            type_expr = cst.parse_expression(type_annotation)

            # Find and update the parameter
            new_params = []
            for param in node.params.params:
                if param.name.value == parameter_name:
                    new_param = param.with_changes(annotation=cst.Annotation(annotation=type_expr))
                    new_params.append(new_param)
                else:
                    new_params.append(param)

            new_parameters = node.params.with_changes(params=new_params)
            return node.with_changes(params=new_parameters)

        except cst.ParserSyntaxError as e:
            raise ValueError(f"Invalid parameter type annotation '{type_annotation}': {e}")

    def _add_return_annotation(self, node: cst.FunctionDef, plan: InsertionPlan) -> cst.FunctionDef:
        """Add return type annotation to function."""
        type_annotation = plan.metadata["type_annotation"]

        try:
            type_expr = cst.parse_expression(type_annotation)
            annotation = cst.Annotation(annotation=type_expr)
            return node.with_changes(returns=annotation)

        except cst.ParserSyntaxError as e:
            raise ValueError(f"Invalid return type annotation '{type_annotation}': {e}")

    def get_execution_summary(self) -> dict[str, object]:
        """Get detailed summary of transformation execution."""
        return {
            "inserted_count": self.inserted_count,
            "failed_count": len(self.failed_insertions),
            "strategy_details": dict(self.execution_details),
            "failed_plans": [
                {
                    "strategy": plan.strategy_name,
                    "target": plan.target.name,
                    "line": plan.target.location.line,
                    "transformation": plan.transformation.value,
                }
                for plan in self.failed_insertions
            ],
        }
