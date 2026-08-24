"""Shared insert-then-compile helpers: apply every variable insertion to source, return new text."""

from __future__ import annotations

from fangtype.insertion import (
    CodeLocation,
    InsertionEngine,
    InsertionTarget,
    TargetType,
)


def _insert_all_variables(source: str, insertions: dict[tuple[int, str], str]) -> str:
    """Apply every variable insertion the inference layer produced, return new source."""
    targets = [
        InsertionTarget(
            target_type=TargetType.VARIABLE_SIMPLE,
            location=CodeLocation(line=line_0 + 1, column=0),  # engine wants 1-based lines
            type_annotation=type_str,
            name=name,
        )
        for (line_0, name), type_str in insertions.items()
    ]
    result = InsertionEngine().insert(targets, source)
    assert result.success
    return result.modified_source
