"""InsertionEngine orchestrates type annotation insertions via strategies and the transformer."""

import logging
from typing import cast

import libcst as cst
from libcst.metadata import PositionProvider

from .strategy import plan_target
from .transformer import UnifiedTransformer
from .types import (
    InsertionContext,
    InsertionPlan,
    InsertionResult,
    InsertionTarget,
)

logger = logging.getLogger(__name__)


class InsertionEngine:
    """Engine that handles all insertion types through strategies."""

    def insert(self, targets: list[InsertionTarget], source: str) -> InsertionResult:
        """Insert type annotations according to the specified targets."""
        if not targets:
            return InsertionResult.success_result(source, 0, {"message": "No targets provided"})

        logger.info(f"Starting insertion for {len(targets)} targets")

        try:
            # 1. Planning Phase
            context = self._create_insertion_context(source)
            plans, failures = self._create_execution_plans(targets, context)

            # Nothing planned -> informative error, keeping the single-target cursor-path message.
            if not plans:
                return InsertionResult.error_result(
                    source, self._describe_failures(failures), [t for t, _ in failures]
                )

            # 2. Execution Phase: apply good plans, record skipped targets instead of aborting all.
            result = self._execute_plans(plans, source)
            if failures:
                # Extend, don't overwrite: _execute_plans already recorded execution failures.
                result.failed_targets = [*result.failed_targets, *(t for t, _ in failures)]
                result.details = {**result.details, "skipped_count": len(failures)}
            return result

        except Exception as e:
            logger.error(f"Insertion failed: {e}", exc_info=True)
            return InsertionResult.error_result(source, str(e), targets)

    def _describe_failures(self, failures: list[tuple[InsertionTarget, str]]) -> str:
        """Build a human-readable summary of planning failures (exact wording is depended on)."""
        error_messages = []
        for target, error in failures:
            if "Invalid type annotation syntax" in error:
                error_messages.append(f"Invalid type annotation syntax: {target.type_annotation}")
            else:
                error_messages.append(f"Failed to plan insertion for {target.name}")

        return "; ".join(error_messages) if error_messages else "Planning failed for some targets"

    def _create_insertion_context(self, source: str) -> InsertionContext:
        """Create context information for insertion strategies."""
        return InsertionContext(
            source=source,
            existing_annotations=self._find_existing_annotations(source),
        )

    def _find_existing_annotations(self, source: str) -> dict[tuple[str, int], str]:
        """Find existing type annotations in the source code, keyed by (name, line)."""
        try:
            wrapper = cst.metadata.MetadataWrapper(cst.parse_module(source))
            visitor = AnnotationFinder()
            wrapper.visit(visitor)
            return visitor.annotations

        except Exception as e:
            logger.debug(f"Could not extract existing annotations: {e}")
            return {}

    def _create_execution_plans(
        self, targets: list[InsertionTarget], context: InsertionContext
    ) -> tuple[list[InsertionPlan], list[tuple[InsertionTarget, str]]]:
        """Create execution plans using appropriate strategies."""
        plans: list[InsertionPlan] = []
        failures: list[tuple[InsertionTarget, str]] = []

        for target in targets:
            try:
                plan = plan_target(target, context)
                if plan is None:
                    msg = f"No strategy found for target: {target.target_type}"
                    logger.warning(msg)
                    failures.append((target, msg))
                    continue

                plans.append(plan)
                logger.debug(f"Created plan for {target.name} using {plan.strategy_name}")

            except Exception as e:
                # Store the error for better error reporting
                msg = str(e)
                logger.warning(f"Failed to plan insertion for {target.name}: {e}")
                failures.append((target, msg))

        if failures:
            logger.warning(f"Failed to plan {len(failures)} insertions")

        return plans, failures

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

            result = InsertionResult.success_result(
                modified_source,
                cast("int", summary["inserted_count"]),
                summary,
            )
            # Plans the transformer rejected are swallowed per-plan; surface them so a caller
            # can't read "success" as "everything landed".
            result.failed_targets = [plan.target for plan in transformer.failed_insertions]
            return result

        except cst.ParserSyntaxError as e:
            error_msg = f"Source parsing failed: {e}"
            logger.error(error_msg)
            return InsertionResult.error_result(source, error_msg)

        except Exception as e:
            error_msg = f"Transformation failed: {e}"
            logger.error(error_msg, exc_info=True)
            return InsertionResult.error_result(source, error_msg)

    def preview_insertions(self, targets: list[InsertionTarget], source: str) -> dict[str, object]:
        """Preview what insertions would be performed without executing them."""
        try:
            context = self._create_insertion_context(source)
            plans, _failures = self._create_execution_plans(targets, context)

            plans_by_strategy: dict[str, int] = {}
            plan_details: list[dict[str, object]] = []

            for plan in plans:
                strategy_name = plan.strategy_name
                plans_by_strategy[strategy_name] = plans_by_strategy.get(strategy_name, 0) + 1

                plan_details.append(
                    {
                        "strategy": strategy_name,
                        "target": plan.target.name,
                        "type": plan.target.type_annotation,
                        "line": plan.target.location.line,
                        "transformation": plan.transformation.value,
                    }
                )

            return {
                "total_plans": len(plans),
                "plans_by_strategy": plans_by_strategy,
                "plan_details": plan_details,
            }

        except Exception as e:
            logger.error(f"Preview failed: {e}")
            return {"error": str(e)}


class AnnotationFinder(cst.CSTVisitor):
    """Visitor to find existing type annotations in source code, keyed by (name, line)."""

    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self) -> None:
        self.annotations: dict[tuple[str, int], str] = {}

    def visit_AnnAssign(self, node: cst.AnnAssign) -> bool:
        """Visit annotated assignments to collect existing annotations."""
        if isinstance(node.target, cst.Name):
            # Key by line too: a bare name matched file-wide made every same-named binding
            # elsewhere plan as REPLACEMENT and get silently dropped.
            line = self.get_metadata(PositionProvider, node).start.line
            annotation_str = cst.Module(
                [cst.SimpleStatementLine([cst.Expr(node.annotation.annotation)])]
            ).code.strip()
            self.annotations[(node.target.value, line)] = annotation_str
        return False  # Don't need to visit children
