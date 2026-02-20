"""Parity tests for indexed target-factory helpers."""

from auto_type.insertion import TargetType
from auto_type.insertion.target_factory import (
    build_source_index,
    detect_assignment_pattern,
    detect_assignment_pattern_indexed,
    find_assignment_target,
    find_assignment_target_indexed,
    find_function_line,
    find_function_line_indexed,
)


def _assert_assignment_parity(source: str, name: str, line_hint_0: int | None) -> None:
    legacy = find_assignment_target(source, name, line_hint_0)
    index = build_source_index(source)
    assert index is not None
    indexed = find_assignment_target_indexed(index, name, line_hint_0)
    assert indexed == legacy


def _assert_pattern_parity(source: str, name: str, line_0: int) -> None:
    legacy = detect_assignment_pattern(source, name, line_0)
    index = build_source_index(source)
    assert index is not None
    indexed = detect_assignment_pattern_indexed(index, name, line_0)
    assert indexed == legacy


def test_assignment_parity_simple_assignment() -> None:
    source = "x = 1\ny = 2\n"
    _assert_assignment_parity(source, "x", 0)


def test_assignment_parity_tuple_unpacking() -> None:
    source = "a, b = get_values()\n"
    _assert_assignment_parity(source, "a", 0)
    _assert_pattern_parity(source, "a", 0)


def test_assignment_parity_for_iteration() -> None:
    source = "for item in seq:\n    pass\n"
    _assert_assignment_parity(source, "item", 0)
    _assert_pattern_parity(source, "item", 0)


def test_assignment_parity_augassign_and_walrus() -> None:
    source = "x = 1\nx += 2\nif (word := 'hello'):\n    pass\n"
    _assert_assignment_parity(source, "x", 1)
    _assert_pattern_parity(source, "x", 1)
    _assert_assignment_parity(source, "word", 2)
    _assert_pattern_parity(source, "word", 2)


def test_assignment_parity_comprehension_iteration() -> None:
    source = "x, y = (i for i in range(3))\n"
    _assert_assignment_parity(source, "i", 0)
    _assert_pattern_parity(source, "i", 0)


def test_assignment_parity_attribute_assignment() -> None:
    source = "self.value = other.attr\n"
    _assert_assignment_parity(source, "self.value", 0)
    _assert_pattern_parity(source, "self.value", 0)


def test_assignment_parity_subscript_rhs() -> None:
    source = "value = data['k']\n"
    _assert_assignment_parity(source, "value", 0)
    _assert_pattern_parity(source, "value", 0)


def test_attribute_augassign_prefers_plain_assignment_candidate() -> None:
    source = "self.n = 0\nself.n += 1\n"
    index = build_source_index(source)
    assert index is not None

    resolved = find_assignment_target_indexed(index, "self.n", 1)
    assert resolved is not None
    assert resolved.line_1_based == 1
    assert resolved.target_type == TargetType.ATTRIBUTE_ACCESS


def test_assignment_uses_line_hint_at_or_before() -> None:
    source = "x = 1\nx = 2\nx = 3\n"
    index = build_source_index(source)
    assert index is not None

    resolved = find_assignment_target_indexed(index, "x", 1)
    assert resolved is not None
    assert resolved.line_1_based == 2


def test_find_function_line_indexed_parity() -> None:
    source = """
def outer():
    def inner():
        return 1

class A:
    async def work(self):
        return 2
"""
    index = build_source_index(source)
    assert index is not None

    assert find_function_line_indexed(index, "outer.inner") == find_function_line(
        source, "outer.inner"
    )
    assert find_function_line_indexed(index, "A.work") == find_function_line(source, "A.work")
    assert find_function_line_indexed(index, "work") == find_function_line(source, "work")


def test_index_none_on_syntax_error_and_legacy_fallback() -> None:
    source = "invalid syntax [["
    assert build_source_index(source) is None
    assert detect_assignment_pattern(source, "x", 0) == TargetType.VARIABLE_SIMPLE
    assert find_function_line(source, "func") == 1
