"""JediProbe — a TypeProbe backed by a Jedi Script (positional inference)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fangtype.inference.jedi.positions import script_byte_col_to_codepoint
from fangtype.inference.jedi.type_formatter import format_types
from fangtype.inference.type_utils import normalize_type_name

if TYPE_CHECKING:
    import ast

    import jedi


class JediProbe:
    """TypeProbe backed by a Jedi Script (positional inference)."""

    def __init__(self, script: jedi.Script) -> None:
        self._script = script

    def infer_expr_type(self, expr: ast.expr) -> str:
        end_line = expr.end_lineno or expr.lineno
        end_cp = script_byte_col_to_codepoint(self._script, end_line, expr.end_col_offset or 1)
        start_cp = script_byte_col_to_codepoint(self._script, expr.lineno, expr.col_offset)
        points = [
            (end_line, max(end_cp - 1, 0)),
            (expr.lineno, start_cp),
        ]
        for line, col in points:
            try:
                inferred = format_types(list(self._script.infer(line, col)))
            except Exception:
                continue
            if inferred and inferred != "Unknown":
                return normalize_type_name(inferred)
        return "Unknown"
