"""Tests for annotated_targets_by_line, the line-keyed PEP 526 annotation index."""

import ast

from fangtype.analysis import annotated_targets_by_line


def test_bare_target_is_recorded_by_name() -> None:
    index = annotated_targets_by_line(ast.parse("x: int = 5\n"))
    assert index == {0: {"x"}}


def test_self_attribute_target_is_recorded_dotted() -> None:
    """The attribute call site asks about ``self.width``, so that is how it is stored."""
    source = "class C:\n    def __init__(self):\n        self.width: int = 5\n"
    index = annotated_targets_by_line(ast.parse(source))
    assert index == {2: {"self.width"}}


def test_non_self_dotted_target_is_recorded_dotted() -> None:
    source = "class C:\n    def __init__(self, point):\n        point.x: int = 5\n"
    index = annotated_targets_by_line(ast.parse(source))
    assert index == {2: {"point.x"}}


def test_bare_declaration_without_a_value_is_recorded() -> None:
    """``total: int`` binds nothing at runtime but still annotates the name."""
    index = annotated_targets_by_line(ast.parse("total: int\n"))
    assert index == {0: {"total"}}


def test_plain_assignment_records_nothing() -> None:
    assert annotated_targets_by_line(ast.parse("x = 5\n")) == {}


def test_subscript_target_is_skipped() -> None:
    """``d["k"]: int`` annotates no name, so it must not enter the index."""
    assert annotated_targets_by_line(ast.parse('d["k"]: int = 5\n')) == {}


def test_lambda_parameter_colon_is_not_an_annotation() -> None:
    """The colon belongs to the lambda's parameter list, not to a binding."""
    assert annotated_targets_by_line(ast.parse("x = lambda x: x + 1\n")) == {}


def test_annotation_in_a_comment_is_not_seen() -> None:
    assert annotated_targets_by_line(ast.parse("x = 5  # x: int\n")) == {}


def test_annotation_inside_a_string_is_not_seen() -> None:
    assert annotated_targets_by_line(ast.parse('s = "x: int"\n')) == {}


def test_nested_def_annotations_keep_their_own_lines() -> None:
    """Walking into a nested def is safe because entries are keyed by line."""
    source = "def outer():\n    a: int = 1\n\n    def inner():\n        b: str = 'x'\n"
    assert annotated_targets_by_line(ast.parse(source)) == {1: {"a"}, 4: {"b"}}


def test_two_annotations_on_one_line_both_land() -> None:
    """A semicolon puts two annotated bindings on one line, and the index is a set."""
    index = annotated_targets_by_line(ast.parse('x: int = 1; y: str = "a"\n'))
    assert index == {0: {"x", "y"}}


def test_empty_module_yields_an_empty_index() -> None:
    """The degraded inference fallback builds a synthetic empty module."""
    assert annotated_targets_by_line(ast.Module(body=[], type_ignores=[])) == {}
