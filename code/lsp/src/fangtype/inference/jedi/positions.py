"""Bridge AST UTF-8 byte columns to Jedi/server code-point columns via the Script's source cache."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fangtype.utils.position_encoding import byte_to_codepoint

if TYPE_CHECKING:
    import jedi


def script_byte_col_to_codepoint(script: jedi.Script, lineno: int, byte_col: int) -> int:
    """Convert byte column on 1-based ``lineno`` to code-point column (raw offset if N/A)."""
    lines = getattr(script, "_code_lines", None)
    if not lines or not (1 <= lineno <= len(lines)):
        return byte_col
    return byte_to_codepoint(lines[lineno - 1], byte_col)
