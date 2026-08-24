"""Tests for column-unit conversions in position_encoding; units diverge past ASCII (é, 😀)."""

import ast

import pytest

from fangtype.utils.position_encoding import (
    ast_source_lines,
    byte_to_codepoint,
    codepoint_to_utf16,
    utf16_to_codepoint,
)

# The three conversions share identical ASCII-identity / clamp / non-positive edge behavior.
_ALL_CONVERSIONS = [
    pytest.param(utf16_to_codepoint, id="utf16_to_codepoint"),
    pytest.param(codepoint_to_utf16, id="codepoint_to_utf16"),
    pytest.param(byte_to_codepoint, id="byte_to_codepoint"),
]


@pytest.mark.parametrize("convert", _ALL_CONVERSIONS)
def test_ascii_is_identity(convert) -> None:
    line = "value = 42"
    for col in range(len(line) + 1):
        assert convert(line, col) == col


@pytest.mark.parametrize("convert", _ALL_CONVERSIONS)
def test_clamps_past_end(convert) -> None:
    assert convert("ab", 99) == 2


@pytest.mark.parametrize("convert", _ALL_CONVERSIONS)
def test_non_positive(convert) -> None:
    assert convert("abc", 0) == 0
    assert convert("abc", -5) == 0


class TestUtf16ToCodepoint:
    def test_accent_before_target(self) -> None:
        # "café_x" — 'é' is 1 UTF-16 unit, so UTF-16 cols still match code points here.
        line = "café_x = 1"
        assert utf16_to_codepoint(line, 4) == 4  # underscore start
        assert utf16_to_codepoint(line, 6) == 6  # '=' via " = "? -> the space after café_x

    def test_astral_shifts_utf16_ahead(self) -> None:
        # "😀ab": 😀 = 2 UTF-16 units. 'a' is UTF-16 col 2, code point 1.
        line = "😀ab"
        assert utf16_to_codepoint(line, 0) == 0
        assert utf16_to_codepoint(line, 2) == 1  # 'a'
        assert utf16_to_codepoint(line, 3) == 2  # 'b'

    def test_inside_surrogate_pair_rounds_up(self) -> None:
        line = "😀ab"
        # col 1 lands inside the surrogate pair -> next code point (index 1).
        assert utf16_to_codepoint(line, 1) == 1


class TestCodepointToUtf16:
    def test_astral_expands(self) -> None:
        line = "😀ab"
        assert codepoint_to_utf16(line, 0) == 0
        assert codepoint_to_utf16(line, 1) == 2  # past 😀 = 2 units
        assert codepoint_to_utf16(line, 2) == 3  # past 'a'

    def test_roundtrip_with_utf16_to_codepoint(self) -> None:
        line = "x = 😀 + café"
        for cp in range(len(line) + 1):
            u16 = codepoint_to_utf16(line, cp)
            # Round-trips for code points that don't sit inside a surrogate pair.
            assert utf16_to_codepoint(line, u16) == cp


class TestByteToCodepoint:
    def test_accent_is_two_bytes(self) -> None:
        # "café": c,a,f = 3 bytes/cps; 'é' = 2 bytes. Byte 5 is just past 'é' -> cp 4.
        line = "café"
        assert byte_to_codepoint(line, 3) == 3  # start of 'é'
        assert byte_to_codepoint(line, 5) == 4  # end of 'é'

    def test_ast_col_offset_semantics(self) -> None:
        # Mirrors ast.col_offset (bytes): "x = café_y" -> 'café_y' starts at byte 4.
        line = "x = café_y"
        # 'café_y' spans bytes 4..(4+7)=11 (é is 2 bytes), code points 4..10.
        assert byte_to_codepoint(line, 4) == 4
        assert byte_to_codepoint(line, 11) == 10

    def test_mid_character_rounds_down(self) -> None:
        # Byte 4 lands in the middle of 'é' (bytes 3-4) -> rounds down to cp 3.
        line = "café"
        assert byte_to_codepoint(line, 4) == 3


class TestAstSourceLines:
    """ast_source_lines must split exactly where Python's tokenizer does, so indices == ast lineno."""

    def test_splits_only_on_python_newlines(self) -> None:
        # \f (form-feed) and \v are NOT line breaks to the tokenizer, unlike str.splitlines().
        source = "a = 1\fb = 2\nc = 3\r\nd = 4\re = 5"
        lines = ast_source_lines(source)
        assert lines == ["a = 1\fb = 2", "c = 3", "d = 4", "e = 5"]

    def test_index_matches_ast_lineno_across_form_feed(self) -> None:
        # A \f inside a string literal keeps the code parseable but makes str.splitlines() over-split
        # and desync; ast_source_lines stays aligned with node.lineno.
        source = 's = "a\fb"\ny = 2\n'
        lines = ast_source_lines(source)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                assert lines[node.lineno - 1].lstrip().startswith(name)
