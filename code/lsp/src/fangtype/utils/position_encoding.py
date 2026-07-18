"""Convert columns between LSP UTF-16, code points, and UTF-8 bytes; clamps overflow to line end."""

from __future__ import annotations

import re

# The AST/tokenizer only breaks lines on \n, \r, \r\n — unlike str.splitlines(), which also
# splits on \v, \f, U+2028, etc. Splitting on those desyncs line indices from node.lineno.
_AST_NEWLINE = re.compile(r"\r\n|\r|\n")


def ast_source_lines(source: str) -> list[str]:
    """Split ``source`` into lines the way Python's tokenizer does (indices match ast lineno)."""
    return _AST_NEWLINE.split(source)


def _utf16_units(ch: str) -> int:
    """UTF-16 code units for a single character: 1 for BMP, 2 for astral (surrogate pair)."""
    return 2 if ord(ch) > 0xFFFF else 1


def utf16_to_codepoint(line_text: str, utf16_col: int) -> int:
    """Convert UTF-16 col to code-point index; clamps past end, rounds mid-surrogate-pair col up."""
    if utf16_col <= 0:
        return 0
    units = 0
    for cp_index, ch in enumerate(line_text):
        if units >= utf16_col:
            return cp_index
        units += _utf16_units(ch)
    return len(line_text)


def codepoint_to_utf16(line_text: str, cp_col: int) -> int:
    """Convert a code-point index to a UTF-16 code-unit column; clamps ``cp_col`` to line length."""
    if cp_col <= 0:
        return 0
    cp_col = min(cp_col, len(line_text))
    return sum(_utf16_units(ch) for ch in line_text[:cp_col])


def byte_to_codepoint(line_text: str, byte_col: int) -> int:
    """Convert a UTF-8 byte offset (ast.col_offset) to a code-point index; clamps, rounds down."""
    if byte_col <= 0:
        return 0
    encoded = line_text.encode("utf-8")
    if byte_col >= len(encoded):
        return len(line_text)
    return len(encoded[:byte_col].decode("utf-8", "ignore"))
