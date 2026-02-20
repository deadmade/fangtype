"""Fallback insertion orchestration for robust single-target annotation.

This module centralizes retry behavior so benchmark and LSP paths can share
one production implementation.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from auto_type.insertion.target_factory import (
    create_variable_target,
    detect_assignment_pattern,
    find_assignment_target,
    find_variable_line,
)
from auto_type.insertion.types import InsertionResult, InsertionTarget, TargetType

if TYPE_CHECKING:
    from auto_type.insertion.engine import UnifiedInsertionEngine


def _derive_subscript_base_names(name: str) -> list[str]:
    """Derive assignable base names from a subscript expression string."""
    try:
        expression = ast.parse(name, mode="eval").body
    except SyntaxError:
        return []

    base_names: list[str] = []
    current = expression
    while isinstance(current, ast.Subscript):
        current = current.value
        if isinstance(current, ast.Name | ast.Attribute):
            try:
                candidate = ast.unparse(current)
            except Exception:
                break
            if candidate not in base_names:
                base_names.append(candidate)
    return base_names


def _create_variable_target_for_case(
    source: str,
    name: str,
    type_annotation: str,
    line_hint_0: int | None = None,
    line_fallback_1: int | None = None,
) -> InsertionTarget:
    """Create an insertion target with assignment pattern detection."""
    resolved = find_assignment_target(source, name, line_hint_0)
    if resolved is not None:
        line = resolved.line_1_based
        target_type = resolved.target_type
    else:
        line = line_fallback_1 if line_fallback_1 is not None else find_variable_line(source, name)
        target_type = detect_assignment_pattern(source, name, line - 1)
    return create_variable_target(name, type_annotation, line, target_type=target_type)


def _build_retry_targets(
    source: str,
    name: str,
    type_annotation: str,
    line_hint_0: int | None,
    line_fallback_1: int | None,
    prefer_iteration_target: bool = False,
) -> list[InsertionTarget]:
    """Build ordered insertion targets from specific to broad fallback."""
    targets: list[InsertionTarget] = []
    seen: set[tuple[TargetType, int, str]] = set()
    can_declare_name = name.isidentifier()

    def add_target(target: InsertionTarget) -> None:
        key = (target.target_type, target.location.line, target.name)
        if key in seen:
            return
        seen.add(key)
        targets.append(target)

    def add_targets_for_name(candidate_name: str) -> None:
        add_target(
            _create_variable_target_for_case(
                source,
                candidate_name,
                type_annotation,
                line_hint_0=line_hint_0,
                line_fallback_1=line_fallback_1,
            )
        )
        if line_fallback_1 is None:
            return
        add_target(
            _create_variable_target_for_case(
                source,
                candidate_name,
                type_annotation,
                line_hint_0=line_fallback_1 - 1,
                line_fallback_1=line_fallback_1,
            )
        )
        if (
            "." in candidate_name
            and not candidate_name.startswith("self.")
            and "[" not in candidate_name
        ):
            short_name = candidate_name.split(".")[-1]
            add_target(
                _create_variable_target_for_case(
                    source,
                    short_name,
                    type_annotation,
                    line_hint_0=line_fallback_1 - 1,
                    line_fallback_1=line_fallback_1,
                )
            )

    add_targets_for_name(name)

    if line_fallback_1 is not None:
        add_target(
            _create_variable_target_for_case(
                source,
                name,
                type_annotation,
                line_hint_0=line_fallback_1 - 1,
                line_fallback_1=line_fallback_1,
            )
        )

        if prefer_iteration_target and can_declare_name:
            add_target(
                create_variable_target(
                    name,
                    type_annotation,
                    line_fallback_1,
                    target_type=TargetType.ITERATION_VARIABLE,
                )
            )

        if can_declare_name:
            add_target(
                create_variable_target(
                    name,
                    type_annotation,
                    line_fallback_1,
                    target_type=TargetType.VARIABLE_COMPLEX,
                )
            )

        for base_name in _derive_subscript_base_names(name):
            if base_name != name:
                add_targets_for_name(base_name)

    return targets


def insert_variable_with_fallbacks(
    insertion_engine: UnifiedInsertionEngine,
    source: str,
    name: str,
    type_annotation: str,
    line_hint_0: int | None,
    line_fallback_1: int | None,
    prefer_iteration_target: bool = False,
) -> InsertionResult:
    """Try insertion with progressively broader target strategies."""
    final_result: InsertionResult | None = None
    for target in _build_retry_targets(
        source,
        name,
        type_annotation,
        line_hint_0=line_hint_0,
        line_fallback_1=line_fallback_1,
        prefer_iteration_target=prefer_iteration_target,
    ):
        result = insertion_engine.insert([target], source)
        final_result = result
        if result.success and result.inserted_count > 0:
            return result

    if final_result is not None:
        return final_result
    return InsertionResult.error_result(source, "Insertion fallback planning produced no targets")
