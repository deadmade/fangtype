"""Unified insertion engine that orchestrates all type annotation insertions.

This module provides the main UnifiedInsertionEngine class that coordinates
all insertion strategies and executes insertions through the unified transformer.
"""

import ast
import logging
from typing import Any, cast

import libcst as cst

from .strategies import create_default_strategies
from .strategy import InsertionStrategy, find_strategy_for_target, validate_strategies
from .transformer import UnifiedTransformer
from .types import (
    CodeLocation,
    InsertionContext,
    InsertionPlan,
    InsertionResult,
    InsertionTarget,
    TargetType,
)

logger = logging.getLogger(__name__)


class UnifiedInsertionEngine:
    """Unified engine that handles all insertion types through strategies."""

    def __init__(self, strategies: list[InsertionStrategy] | None = None) -> None:
        """Initialize the engine with insertion strategies.

        Args:
            strategies: List of insertion strategies to use, defaults to all built-in strategies
        """
        self._strategies = strategies if strategies is not None else create_default_strategies()
        validate_strategies(self._strategies)

        logger.info(
            f"Initialized with {len(self._strategies)} strategies: "
            f"{[s.name for s in self._strategies]}"
        )

    def insert(self, targets: list[InsertionTarget], source: str) -> InsertionResult:
        """Insert type annotations according to the specified targets."""
        if not targets:
            return InsertionResult.success_result(source, 0, {"message": "No targets provided"})

        logger.info(f"Starting insertion for {len(targets)} targets")

        try:
            # 1. Planning Phase
            context = self._create_insertion_context(source)
            plans, failures = self._create_execution_plans(targets, context)

            # If any targets failed, return error result
            if failures:
                error_messages = []
                failed_targets = []
                for target, error in failures:
                    failed_targets.append(target)
                    if "Invalid type annotation syntax" in error:
                        error_messages.append(
                            f"Invalid type annotation syntax: {target.type_annotation}"
                        )
                    else:
                        error_messages.append(f"Failed to plan insertion for {target.name}")

                error_message = (
                    "; ".join(error_messages)
                    if error_messages
                    else "Planning failed for some targets"
                )
                return InsertionResult.error_result(source, error_message, failed_targets)

            # 2. Dependency Resolution
            ordered_plans = self._resolve_dependencies(plans)

            # 3. Execution Phase
            return self._execute_plans(ordered_plans, source)

        except Exception as e:
            logger.error(f"Insertion failed: {e}", exc_info=True)
            return InsertionResult.error_result(source, str(e), targets)

    def _create_insertion_context(self, source: str) -> InsertionContext:
        """Create context information for insertion strategies."""
        try:
            # Parse source to get AST for context
            ast_tree = ast.parse(source)

            # Find existing annotations
            existing_annotations = self._find_existing_annotations(source)

            return InsertionContext(
                source=source,
                existing_annotations=existing_annotations,
                ast_tree=ast_tree,
                scope_info={},
            )

        except SyntaxError as e:
            logger.warning(f"Failed to parse source for context: {e}")
            # Return minimal context if parsing fails
            return InsertionContext(source=source)

    def _find_existing_annotations(self, source: str) -> dict[str, str]:
        """Find existing type annotations in the source code."""
        existing: dict[str, str] = {}

        try:
            tree = cst.parse_module(source)
            visitor = AnnotationFinder()
            tree.visit(visitor)

            for name, annotation in visitor.annotations.items():
                existing[name] = annotation

        except Exception as e:
            logger.debug(f"Could not extract existing annotations: {e}")

        return existing

    def _create_execution_plans(
        self, targets: list[InsertionTarget], context: InsertionContext
    ) -> tuple[list[InsertionPlan], list[tuple[InsertionTarget, str]]]:
        """Create execution plans using appropriate strategies."""
        plans: list[InsertionPlan] = []
        failures: list[tuple[InsertionTarget, str]] = []

        for target in targets:
            try:
                strategy = find_strategy_for_target(self._strategies, target)
                if strategy is None:
                    msg = f"No strategy found for target: {target.target_type}"
                    logger.warning(msg)
                    failures.append((target, msg))
                    continue

                plan = strategy.plan_insertion(target, context)
                plans.append(plan)
                logger.debug(f"Created plan for {target.name} using {strategy.name}")

            except Exception as e:
                # Store the error for better error reporting
                msg = str(e)
                logger.warning(f"Failed to plan insertion for {target.name}: {e}")
                failures.append((target, msg))

        if failures:
            logger.warning(f"Failed to plan {len(failures)} insertions")

        return plans, failures

    def _resolve_dependencies(self, plans: list[InsertionPlan]) -> list[InsertionPlan]:
        """Resolve dependencies and sort plans by execution priority."""
        # For now, use simple priority-based sorting
        # Future enhancement: implement full dependency graph resolution
        return sorted(plans, key=lambda p: p.priority, reverse=True)

    def _execute_plans(self, plans: list[InsertionPlan], source: str) -> InsertionResult:
        """Execute all plans in a single LibCST transformation."""
        if not plans:
            return InsertionResult.success_result(
                modified_source=source, inserted_count=0, details={"message": "No plans to execute"}
            )

        try:
            # Parse the source
            tree = cst.parse_module(source)

            # Create and apply the unified transformer using MetadataWrapper
            wrapper = cst.metadata.MetadataWrapper(tree)
            transformer = UnifiedTransformer(plans)

            # Apply transformation
            modified_tree = wrapper.visit(transformer)

            # Generate the modified source
            modified_source = modified_tree.code

            # Get execution summary
            summary = transformer.get_execution_summary()

            logger.info(
                f"Execution completed: {summary['inserted_count']} insertions, "
                f"{summary['failed_count']} failures"
            )

            return InsertionResult.success_result(
                modified_source,
                cast("int", summary["inserted_count"]),
                summary,
            )

        except cst.ParserSyntaxError as e:
            error_msg = f"Source parsing failed: {e}"
            logger.error(error_msg)
            return InsertionResult.error_result(source, error_msg)

        except Exception as e:
            error_msg = f"Transformation failed: {e}"
            logger.error(error_msg, exc_info=True)
            return InsertionResult.error_result(source, error_msg)

    # Convenience methods for backward compatibility and ease of use

    def insert_variable_annotation(
        self, source: str, variable_name: str, type_annotation: str, line: int, column: int = 0
    ) -> InsertionResult:
        """Insert a single variable annotation."""
        target = InsertionTarget(
            target_type=TargetType.VARIABLE_SIMPLE,
            location=CodeLocation(line=line, column=column),
            type_annotation=type_annotation,
            name=variable_name,
        )
        return self.insert([target], source)

    def insert_function_parameter_annotation(
        self,
        source: str,
        function_name: str,
        parameter_name: str,
        type_annotation: str,
        line: int,
        column: int = 0,
    ) -> InsertionResult:
        """Insert a function parameter annotation."""
        target = InsertionTarget(
            target_type=TargetType.FUNCTION_PARAMETER,
            location=CodeLocation(line=line, column=column),
            type_annotation=type_annotation,
            name=parameter_name,
            metadata={"function_name": function_name},
        )
        return self.insert([target], source)

    def insert_function_return_annotation(
        self, source: str, function_name: str, type_annotation: str, line: int, column: int = 0
    ) -> InsertionResult:
        """Insert a function return type annotation."""
        target = InsertionTarget(
            target_type=TargetType.FUNCTION_RETURN,
            location=CodeLocation(line=line, column=column),
            type_annotation=type_annotation,
            name=function_name,
        )
        return self.insert([target], source)

    def preview_insertions(self, targets: list[InsertionTarget], source: str) -> dict[str, Any]:
        """Preview what insertions would be performed without executing them."""
        try:
            context = self._create_insertion_context(source)
            plans, _failures = self._create_execution_plans(targets, context)
            ordered_plans = self._resolve_dependencies(plans)

            preview: dict[str, Any] = {
                "total_plans": len(ordered_plans),
                "plans_by_strategy": {},
                "plan_details": [],
            }

            for plan in ordered_plans:
                strategy_name = plan.strategy_name
                if strategy_name not in preview["plans_by_strategy"]:
                    preview["plans_by_strategy"][strategy_name] = 0
                preview["plans_by_strategy"][strategy_name] += 1

                preview["plan_details"].append(
                    {
                        "strategy": strategy_name,
                        "target": plan.target.name,
                        "type": plan.target.type_annotation,
                        "line": plan.target.location.line,
                        "transformation": plan.transformation.value,
                    }
                )

            return preview

        except Exception as e:
            logger.error(f"Preview failed: {e}")
            return {"error": str(e)}


class AnnotationFinder(cst.CSTVisitor):
    """Visitor to find existing type annotations in source code."""

    def __init__(self) -> None:
        self.annotations: dict[str, str] = {}

    def visit_AnnAssign(self, node: cst.AnnAssign) -> bool:
        """Visit annotated assignments to collect existing annotations."""
        if isinstance(node.target, cst.Name):
            var_name = node.target.value
            # Convert annotation back to string
            annotation_str = cst.Module(
                [cst.SimpleStatementLine([cst.Expr(node.annotation.annotation)])]
            ).code.strip()
            self.annotations[var_name] = annotation_str
        return False  # Don't need to visit children

    def visit_FunctionDef(self, node: cst.FunctionDef) -> bool:
        """Visit function definitions to collect parameter and return annotations."""
        # Collect parameter annotations
        for param in node.params.params:
            if param.annotation is not None:
                param_name = param.name.value
                annotation_str = cst.Module(
                    [cst.SimpleStatementLine([cst.Expr(param.annotation.annotation)])]
                ).code.strip()
                self.annotations[param_name] = annotation_str

        # Collect return annotation
        if node.returns is not None:
            func_name = node.name.value
            return_annotation_str = cst.Module(
                [cst.SimpleStatementLine([cst.Expr(node.returns.annotation)])]
            ).code.strip()
            self.annotations[f"{func_name}__return__"] = return_annotation_str

        return True  # Continue visiting children for nested functions
