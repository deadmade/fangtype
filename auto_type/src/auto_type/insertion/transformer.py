"""Unified LibCST transformer that executes all insertion plans.

This module contains the UnifiedTransformer class that performs all
type annotation insertions in a single pass through the LibCST tree.
"""

import logging
from collections import defaultdict
from typing import Literal

import libcst as cst
from libcst.metadata import PositionProvider

from .types import InsertionPlan, InsertionPlanMetadata, TargetType, TransformationType

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
        # Get line number for this statement (1-based)
        pos = self.get_metadata(PositionProvider, original_node)
        line_number = pos.start.line

        # Find plans that match this statement's line and variable
        matching_plans = []
        for plan in self._plans:
            if (
                plan.transformation
                in (
                    TransformationType.IN_PLACE,
                    TransformationType.REPLACEMENT,
                    TransformationType.DECLARATION,
                )
                and plan.target.location.line == line_number
                and (
                    self._statement_contains_variable(updated_node, plan.target.name)
                    or plan.target.target_type == TargetType.ITERATION_VARIABLE
                )
            ):
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
                return cst.FlattenSentinel([*declaration_statements, modified_node])

        return modified_node

    def _require_metadata_str(
        self,
        metadata: InsertionPlanMetadata,
        key: Literal[
            "type_annotation",
            "variable_name",
            "new_type",
            "parameter_name",
        ],
    ) -> str:
        """Get a required string value from plan metadata."""
        value = metadata.get(key)
        if not isinstance(value, str):
            raise ValueError(f"Missing or invalid metadata '{key}'")
        return value

    def _get_annotation_kind(self, metadata: InsertionPlanMetadata) -> str | None:
        """Get validated annotation kind from metadata."""
        value = metadata.get("annotation_kind")
        if value in ("parameter", "return"):
            return value
        return None

    def _statement_contains_variable(
        self, node: cst.SimpleStatementLine, variable_name: str
    ) -> bool:
        """Check if a statement contains an assignment to the given variable."""
        for stmt in node.body:
            if isinstance(stmt, cst.Assign):
                for target in stmt.targets:
                    if self._assign_target_contains_variable(target.target, variable_name):
                        return True
            elif (
                isinstance(stmt, cst.AugAssign)
                and self._assign_target_contains_variable(stmt.target, variable_name)
            ) or (
                isinstance(stmt, cst.AnnAssign)
                and self._get_full_name(stmt.target) == variable_name
            ):
                return True
        return False

    def _assign_target_contains_variable(
        self, target: cst.BaseAssignTargetExpression, variable_name: str
    ) -> bool:
        """Check if an assignment target contains a specific variable."""
        if self._get_full_name(target) == variable_name:
            return True
        if isinstance(target, cst.Tuple | cst.List):
            for element in target.elements:
                if isinstance(element, cst.StarredElement):
                    value = element.value
                elif isinstance(element, cst.Element):
                    value = element.value
                    if isinstance(value, cst.StarredElement):
                        value = value.value
                else:
                    continue
                if isinstance(
                    value, cst.BaseAssignTargetExpression
                ) and self._assign_target_contains_variable(value, variable_name):
                    return True
        return False

    def _for_contains_variable(self, node: cst.For, variable_name: str) -> bool:
        """Check if a for-loop target contains the given variable."""
        return self._for_target_contains_variable(node.target, variable_name)

    def _for_target_contains_variable(self, target: cst.CSTNode, variable_name: str) -> bool:
        """Check if a for-loop assignment target contains the given variable."""
        full_name = self._get_full_name(target)
        if full_name == variable_name:
            return True

        if isinstance(target, cst.Tuple | cst.List):
            for element in target.elements:
                if not isinstance(element, cst.Element):
                    continue
                value = element.value
                if isinstance(value, cst.StarredElement):
                    if self._for_target_contains_variable(value.value, variable_name):
                        return True
                    continue
                if isinstance(value, cst.CSTNode) and self._for_target_contains_variable(
                    value, variable_name
                ):
                    return True
        return False

    def _while_contains_variable(self, node: cst.While, variable_name: str) -> bool:
        """Check whether a while condition contains the target variable name."""
        condition_code = cst.Module([]).code_for_node(node.test)
        return variable_name in condition_code

    def _get_full_name(self, node: cst.CSTNode) -> str | None:
        """Get full name from Name or Attribute node (e.g., 'x' or 'self.attr')."""
        if isinstance(node, cst.Name):
            return node.value
        if isinstance(node, cst.Attribute):
            base = self._get_full_name(node.value)
            if base:
                return f"{base}.{node.attr.value}"
        return None

    def leave_FunctionDef(
        self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef
    ) -> cst.FunctionDef:
        """Handle function signature insertions."""
        # Get line number for this function definition (1-based)
        pos = self.get_metadata(PositionProvider, original_node)
        line_number = pos.start.line

        # Find plans that match this function's line and name
        function_name = original_node.name.value
        matching_plans = []

        for plan in self._plans:
            if (
                plan.transformation == TransformationType.FUNCTION_SIGNATURE
                and plan.target.location.line == line_number
                and (
                    (
                        plan.target.target_type == TargetType.FUNCTION_RETURN
                        and plan.target.name == function_name
                    )
                    or (
                        plan.target.target_type == TargetType.FUNCTION_PARAMETER
                        and self._function_has_parameter(original_node, plan.target.name)
                    )
                )
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
                annotation_kind = self._get_annotation_kind(plan.metadata) or "unknown"
                self.execution_details[plan.strategy_name].append(
                    f"{plan.target.name} ({annotation_kind})"
                )
            except Exception as e:
                self._logger.warning(f"Failed to apply function plan for {plan.target.name}: {e}")
                self.failed_insertions.append(plan)

        return modified_node

    def leave_For(
        self, original_node: cst.For, updated_node: cst.For
    ) -> cst.For | cst.FlattenSentinel[cst.BaseStatement]:
        """Insert declaration plans before matching for-loops."""
        pos = self.get_metadata(PositionProvider, original_node)
        line_number = pos.start.line
        declaration_plans = [
            plan
            for plan in self._plans
            if (
                plan.transformation == TransformationType.DECLARATION
                and plan.target.location.line == line_number
                and self._for_contains_variable(original_node, plan.target.name)
            )
        ]
        if not declaration_plans:
            return updated_node

        declaration_statements: list[cst.SimpleStatementLine] = []
        for plan in declaration_plans:
            try:
                declaration_stmt = self._create_declaration_statement(plan)
                declaration_statements.append(declaration_stmt)
                self.inserted_count += 1
                self.execution_details[plan.strategy_name].append(
                    f"{plan.target.name} (declaration)"
                )
            except Exception as e:
                self._logger.warning(f"Failed to create declaration for {plan.target.name}: {e}")
                self.failed_insertions.append(plan)

        if not declaration_statements:
            return updated_node
        return cst.FlattenSentinel([*declaration_statements, updated_node])

    def leave_While(
        self, original_node: cst.While, updated_node: cst.While
    ) -> cst.While | cst.FlattenSentinel[cst.BaseStatement]:
        """Insert declaration plans before matching while-loops."""
        pos = self.get_metadata(PositionProvider, original_node)
        line_number = pos.start.line
        declaration_plans = [
            plan
            for plan in self._plans
            if (
                plan.transformation == TransformationType.DECLARATION
                and plan.target.location.line == line_number
                and self._while_contains_variable(original_node, plan.target.name)
            )
        ]
        if not declaration_plans:
            return updated_node

        declaration_statements: list[cst.SimpleStatementLine] = []
        for plan in declaration_plans:
            try:
                declaration_stmt = self._create_declaration_statement(plan)
                declaration_statements.append(declaration_stmt)
                self.inserted_count += 1
                self.execution_details[plan.strategy_name].append(
                    f"{plan.target.name} (declaration)"
                )
            except Exception as e:
                self._logger.warning(f"Failed to create declaration for {plan.target.name}: {e}")
                self.failed_insertions.append(plan)

        if not declaration_statements:
            return updated_node
        return cst.FlattenSentinel([*declaration_statements, updated_node])

    def _function_has_parameter(self, node: cst.FunctionDef, parameter_name: str) -> bool:
        """Check if a function has a parameter across all parameter kinds."""
        all_params: list[cst.Param] = [
            *node.params.params,
            *node.params.posonly_params,
            *node.params.kwonly_params,
        ]
        if isinstance(node.params.star_arg, cst.Param):
            all_params.append(node.params.star_arg)
        if isinstance(node.params.star_kwarg, cst.Param):
            all_params.append(node.params.star_kwarg)
        return any(param.name.value == parameter_name for param in all_params)

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
        type_annotation = self._require_metadata_str(plan.metadata, "type_annotation")

        # Find the assignment statement for this variable
        for i, statement in enumerate(node.body):
            if isinstance(statement, cst.SimpleStatementSuite):
                continue  # Skip compound statements

            if isinstance(statement, cst.Assign):
                # Check if this assignment targets our variable
                for target in statement.targets:
                    if self._get_full_name(target.target) == variable_name:
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
                            raise ValueError(
                                f"Invalid type annotation '{type_annotation}': {e}"
                            ) from e

        # If we get here, we didn't find the assignment
        raise ValueError(f"Could not find assignment for variable '{variable_name}'")

    def _apply_replacement_transformation(
        self, node: cst.SimpleStatementLine, plan: InsertionPlan
    ) -> cst.SimpleStatementLine:
        """Replace existing annotation: x: old_type = value -> x: new_type = value"""
        variable_name = plan.target.name
        new_type = self._require_metadata_str(plan.metadata, "new_type")

        # Find the annotated assignment for this variable
        for i, statement in enumerate(node.body):
            if isinstance(statement, cst.AnnAssign) and (
                self._get_full_name(statement.target) == variable_name
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
                    raise ValueError(f"Invalid type annotation '{new_type}': {e}") from e

        raise ValueError(f"Could not find existing annotation for variable '{variable_name}'")

    def _create_declaration_statement(self, plan: InsertionPlan) -> cst.SimpleStatementLine:
        """Create standalone declaration: var_name: type"""
        variable_name = self._require_metadata_str(plan.metadata, "variable_name")
        type_annotation = self._require_metadata_str(plan.metadata, "type_annotation")

        try:
            target_expr = cst.parse_expression(variable_name)
            if not isinstance(target_expr, cst.BaseAssignTargetExpression):
                raise ValueError(f"Unsupported declaration target '{variable_name}'")
            type_expr = cst.parse_expression(type_annotation)
            ann_assign = cst.AnnAssign(
                target=target_expr,
                annotation=cst.Annotation(annotation=type_expr),
                value=None,  # Declaration only, no value
            )

            return cst.SimpleStatementLine(body=[ann_assign])

        except cst.ParserSyntaxError as e:
            raise ValueError(f"Invalid type annotation '{type_annotation}': {e}") from e

    def _apply_function_plan(self, node: cst.FunctionDef, plan: InsertionPlan) -> cst.FunctionDef:
        """Apply function signature annotation plan."""
        annotation_kind = self._get_annotation_kind(plan.metadata)

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
        parameter_name = self._require_metadata_str(plan.metadata, "parameter_name")
        type_annotation = self._require_metadata_str(plan.metadata, "type_annotation")

        try:
            type_expr = cst.parse_expression(type_annotation)
            annotation = cst.Annotation(annotation=type_expr)

            def update_param_list(
                params: list[cst.Param],
            ) -> tuple[list[cst.Param], bool]:
                updated_params: list[cst.Param] = []
                found = False
                for param in params:
                    if param.name.value == parameter_name:
                        updated_params.append(param.with_changes(annotation=annotation))
                        found = True
                    else:
                        updated_params.append(param)
                return updated_params, found

            new_params, found = update_param_list(list(node.params.params))
            new_posonly, found_posonly = update_param_list(list(node.params.posonly_params))
            found = found or found_posonly
            new_kwonly, found_kwonly = update_param_list(list(node.params.kwonly_params))
            found = found or found_kwonly

            star_arg = node.params.star_arg
            if (
                not found
                and isinstance(star_arg, cst.Param)
                and star_arg.name.value == parameter_name
            ):
                star_arg = star_arg.with_changes(annotation=annotation)
                found = True

            star_kwarg = node.params.star_kwarg
            if (
                not found
                and isinstance(star_kwarg, cst.Param)
                and star_kwarg.name.value == parameter_name
            ):
                star_kwarg = star_kwarg.with_changes(annotation=annotation)
                found = True

            if not found:
                raise ValueError(f"Parameter '{parameter_name}' not found")

            new_parameters = node.params.with_changes(
                params=new_params,
                posonly_params=new_posonly,
                kwonly_params=new_kwonly,
                star_arg=star_arg,
                star_kwarg=star_kwarg,
            )
            return node.with_changes(params=new_parameters)

        except cst.ParserSyntaxError as e:
            raise ValueError(f"Invalid parameter type annotation '{type_annotation}': {e}") from e

    def _add_return_annotation(self, node: cst.FunctionDef, plan: InsertionPlan) -> cst.FunctionDef:
        """Add return type annotation to function."""
        type_annotation = self._require_metadata_str(plan.metadata, "type_annotation")

        try:
            type_expr = cst.parse_expression(type_annotation)
            annotation = cst.Annotation(annotation=type_expr)
            return node.with_changes(returns=annotation)

        except cst.ParserSyntaxError as e:
            raise ValueError(f"Invalid return type annotation '{type_annotation}': {e}") from e

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
