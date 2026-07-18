"""Insertion planning: map an InsertionTarget to the InsertionPlan the transformer executes."""

import logging
from typing import cast

import libcst as cst

from fangtype.inference.type_utils import sanitize_inferred_type

from .types import (
    InsertionContext,
    InsertionPlan,
    InsertionPlanMetadata,
    InsertionTarget,
    TargetType,
    TransformationType,
)

logger = logging.getLogger(__name__)


def validate_type_syntax(type_str: str) -> bool:
    """Return whether the type annotation string parses as a LibCST expression."""
    try:
        cst.parse_expression(type_str.strip())
        return True
    except cst.ParserSyntaxError as e:
        logger.debug(f"Invalid type syntax '{type_str}': {e}")
        return False
    except Exception as e:
        logger.warning(f"Unexpected error validating type '{type_str}': {e}")
        return False


def sanitize_type_annotation(type_str: str) -> str:
    """Return a syntactically valid annotation, salvaging via sanitize_inferred_type; else raise."""
    raw_type = type_str.strip()
    if validate_type_syntax(raw_type):
        return raw_type

    sanitized = sanitize_inferred_type(raw_type).strip()
    if sanitized != raw_type and validate_type_syntax(sanitized):
        logger.debug("Sanitized invalid type '%s' -> '%s'", raw_type, sanitized)
        return sanitized

    raise ValueError(f"Invalid type annotation syntax: {type_str}")


# Stable name per target type; surfaces in preview `plans_by_strategy` and execution summary.
_STRATEGY_NAME: dict[TargetType, str] = {
    TargetType.VARIABLE_SIMPLE: "variable_assignment",
    TargetType.VARIABLE_COMPLEX: "complex_assignment",
    TargetType.FUNCTION_PARAMETER: "function_parameter",
    TargetType.FUNCTION_RETURN: "function_return",
    TargetType.SUBSCRIPT_ACCESS: "subscript_access",
    TargetType.ATTRIBUTE_ACCESS: "attribute_access",
    TargetType.ITERATION_VARIABLE: "iteration_variable",
}

# Transformation for a NEW (not-yet-annotated) binding. An already-annotated binding always
# becomes REPLACEMENT instead. Function params/returns are handled separately below.
_NEW_TRANSFORMATION: dict[TargetType, TransformationType] = {
    TargetType.VARIABLE_SIMPLE: TransformationType.IN_PLACE,
    TargetType.SUBSCRIPT_ACCESS: TransformationType.IN_PLACE,
    TargetType.ATTRIBUTE_ACCESS: TransformationType.IN_PLACE,
    TargetType.VARIABLE_COMPLEX: TransformationType.DECLARATION,
    TargetType.ITERATION_VARIABLE: TransformationType.DECLARATION,
}


def _make_plan(
    target: InsertionTarget, transformation: TransformationType, **metadata: object
) -> InsertionPlan:
    """Build an InsertionPlan stamped with the target's stable strategy name."""
    plan = InsertionPlan(
        strategy_name=_STRATEGY_NAME[target.target_type],
        target=target,
        transformation=transformation,
        metadata=cast("InsertionPlanMetadata", dict(metadata)),
    )
    logger.debug(
        f"Planning {target.target_type.value} insertion for '{target.name}' "
        f"at line {target.location.line}: {transformation.value}"
    )
    return plan


def plan_target(target: InsertionTarget, context: InsertionContext) -> InsertionPlan | None:
    """Plan the insertion for one target, or None if its target type is unsupported.

    Raises ValueError if the type annotation cannot be sanitized into valid syntax.
    """
    if target.target_type == TargetType.FUNCTION_PARAMETER:
        type_annotation = sanitize_type_annotation(target.type_annotation)
        return _make_plan(
            target,
            TransformationType.FUNCTION_SIGNATURE,
            parameter_name=target.name,
            type_annotation=type_annotation,
            annotation_kind="parameter",
        )

    if target.target_type == TargetType.FUNCTION_RETURN:
        type_annotation = sanitize_type_annotation(target.type_annotation)
        return _make_plan(
            target,
            TransformationType.FUNCTION_SIGNATURE,
            type_annotation=type_annotation,
            annotation_kind="return",
        )

    new_transformation = _NEW_TRANSFORMATION.get(target.target_type)
    if new_transformation is None:
        return None

    type_annotation = sanitize_type_annotation(target.type_annotation)

    if context.has_annotation(target.name, target.location.line):
        return _make_plan(target, TransformationType.REPLACEMENT, new_type=type_annotation)

    if new_transformation == TransformationType.IN_PLACE:
        return _make_plan(
            target,
            TransformationType.IN_PLACE,
            variable_name=target.name,
            type_annotation=type_annotation,
        )

    return _make_plan(
        target,
        TransformationType.DECLARATION,
        variable_name=target.name,
        type_annotation=type_annotation,
    )
