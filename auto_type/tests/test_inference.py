"""Tests for literal type inference engine."""

import pytest

from auto_type.inference import LiteralInferenceEngine


@pytest.fixture
def engine():
    """Create a LiteralInferenceEngine instance."""
    return LiteralInferenceEngine()


def test_infer_int_literal(engine):
    """Test inference of integer literals."""
    source = "x = 42"
    types = engine.infer_variable_types(source)
    assert types == {"x": "int"}


def test_infer_string_literal(engine):
    """Test inference of string literals."""
    source = 'name = "hello"'
    types = engine.infer_variable_types(source)
    assert types == {"name": "str"}


def test_infer_bool_literal(engine):
    """Test inference of boolean literals."""
    source = "flag = True"
    types = engine.infer_variable_types(source)
    assert types == {"flag": "bool"}


def test_infer_float_literal(engine):
    """Test inference of float literals."""
    source = "pi = 3.14"
    types = engine.infer_variable_types(source)
    assert types == {"pi": "float"}


def test_infer_list_literal(engine):
    """Test inference of list literals."""
    source = "items = [1, 2, 3]"
    types = engine.infer_variable_types(source)
    assert types == {"items": "list"}


def test_infer_empty_list(engine):
    """Test inference of empty list."""
    source = "items = []"
    types = engine.infer_variable_types(source)
    assert types == {"items": "list"}


def test_infer_dict_literal(engine):
    """Test inference of dict literals."""
    source = "data = {'key': 'value'}"
    types = engine.infer_variable_types(source)
    assert types == {"data": "dict"}


def test_infer_empty_dict(engine):
    """Test inference of empty dict."""
    source = "data = {}"
    types = engine.infer_variable_types(source)
    assert types == {"data": "dict"}


def test_infer_set_literal(engine):
    """Test inference of set literals."""
    source = "numbers = {1, 2, 3}"
    types = engine.infer_variable_types(source)
    assert types == {"numbers": "set"}


def test_infer_tuple_literal(engine):
    """Test inference of tuple literals."""
    source = "coords = (1, 2)"
    types = engine.infer_variable_types(source)
    assert types == {"coords": "tuple"}


def test_infer_none_literal(engine):
    """Test inference of None literal."""
    source = "result = None"
    types = engine.infer_variable_types(source)
    assert types == {"result": "None"}


def test_infer_list_comprehension(engine):
    """Test inference of list comprehensions."""
    source = "squares = [x*x for x in range(10)]"
    types = engine.infer_variable_types(source)
    assert types == {"squares": "list"}


def test_infer_dict_comprehension(engine):
    """Test inference of dict comprehensions."""
    source = "mapping = {k: v for k, v in items}"
    types = engine.infer_variable_types(source)
    assert types == {"mapping": "dict"}


def test_infer_set_comprehension(engine):
    """Test inference of set comprehensions."""
    source = "unique = {x for x in items}"
    types = engine.infer_variable_types(source)
    assert types == {"unique": "set"}


def test_infer_multiple_variables(engine):
    """Test inference of multiple variables."""
    source = """
x = 42
name = "test"
flag = True
items = []
"""
    types = engine.infer_variable_types(source)
    assert types == {"x": "int", "name": "str", "flag": "bool", "items": "list"}


def test_ignore_complex_expressions(engine):
    """Test that complex expressions are ignored."""
    source = "result = func_call()"
    types = engine.infer_variable_types(source)
    assert types == {}


def test_ignore_variable_references(engine):
    """Test that variable references are ignored."""
    source = "y = x"
    types = engine.infer_variable_types(source)
    assert types == {}


def test_skip_already_annotated(engine):
    """Test that annotated assignments are skipped."""
    source = "x: int = 42"
    types = engine.infer_variable_types(source)
    # Should not return anything for already annotated variables
    assert "x" not in types


def test_handle_syntax_error(engine):
    """Test graceful handling of syntax errors."""
    source = "x = "
    types = engine.infer_variable_types(source)
    assert types == {}


def test_get_variable_positions(engine):
    """Test extraction of variable positions."""
    source = """x = 42
name = "test"
"""
    positions = engine.get_variable_positions(source)
    assert "x" in positions
    assert "name" in positions
    # Line 0, column 0 for 'x'
    assert positions["x"] == (0, 0)
    # Line 1, column 0 for 'name'
    assert positions["name"] == (1, 0)


def test_multiline_source(engine):
    """Test inference with multiline source."""
    source = """
def func():
    x = 42
    return x

y = "test"
"""
    types = engine.infer_variable_types(source)
    # Should infer both function-local and module-level variables
    assert "x" in types
    assert "y" in types
    assert types["x"] == "int"
    assert types["y"] == "str"
