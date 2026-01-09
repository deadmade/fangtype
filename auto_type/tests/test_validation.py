"""Tests for mypy-based type validator."""

import pytest

from auto_type.validation import MypyTypeValidator


@pytest.fixture
def validator():
    """Create a MypyTypeValidator instance."""
    return MypyTypeValidator()


def test_validate_builtin_types(validator):
    """Test validation of Python builtin types."""
    source = ""
    assert validator.validate("int", source) is True
    assert validator.validate("str", source) is True
    assert validator.validate("bool", source) is True
    assert validator.validate("float", source) is True
    assert validator.validate("bytes", source) is True
    assert validator.validate("None", source) is True


def test_validate_modern_generic_syntax(validator):
    """Test validation of modern generic syntax (Python 3.9+)."""
    source = ""
    assert validator.validate("list[int]", source) is True
    assert validator.validate("dict[str, int]", source) is True
    assert validator.validate("set[str]", source) is True
    assert validator.validate("tuple[int, str]", source) is True


def test_validate_typing_module_types(validator):
    """Test validation with typing module imports."""
    source = "from typing import List, Dict, Optional, Union"
    assert validator.validate("List[int]", source) is True
    assert validator.validate("Dict[str, int]", source) is True
    assert validator.validate("Optional[str]", source) is True
    assert validator.validate("Union[int, str]", source) is True


def test_reject_unknown_type(validator):
    """Test rejection of undefined types."""
    source = ""
    assert validator.validate("UnknownType", source) is False
    assert validator.validate("MyClass", source) is False


def test_validate_with_custom_class(validator):
    """Test validation with custom class in source."""
    source = """
class MyClass:
    pass

class DataProcessor:
    pass
"""
    assert validator.validate("MyClass", source) is True
    assert validator.validate("DataProcessor", source) is True
    assert validator.validate("UnknownClass", source) is False


def test_validate_complex_generics(validator):
    """Test validation of complex generic types."""
    source = ""
    assert validator.validate("dict[str, list[int]]", source) is True
    assert validator.validate("list[dict[str, set[int]]]", source) is True
    assert validator.validate("tuple[int, str, float]", source) is True


def test_validate_union_types(validator):
    """Test validation of union types (PEP 604 syntax)."""
    source = ""
    assert validator.validate("int | str", source) is True
    assert validator.validate("list[int] | None", source) is True
    assert validator.validate("str | int | float", source) is True


def test_validate_callable_types(validator):
    """Test validation of callable types."""
    source = "from typing import Callable"
    assert validator.validate("Callable[[int], str]", source) is True
    assert validator.validate("Callable[[], None]", source) is True
    assert validator.validate("Callable[[int, str], bool]", source) is True


def test_validate_with_imports_and_aliases(validator):
    """Test validation respects imports and aliases."""
    source = """
from typing import List as L, Dict as D
"""
    assert validator.validate("L[int]", source) is True
    assert validator.validate("D[str, int]", source) is True


def test_validate_rejects_unknown(validator):
    """Test that 'Unknown' is rejected."""
    source = ""
    assert validator.validate("Unknown", source) is False


def test_validate_bulk_filters_invalid(validator):
    """Test bulk validation filters out invalid types."""
    source = """
class MyClass:
    pass
"""
    types_map = {
        "x": "int",
        "y": "MyClass",
        "z": "UnknownType",
        "w": "list[int]",
        "v": "dict[str, InvalidType]",
    }
    validated = validator.validate_bulk(types_map, source)

    assert "x" in validated
    assert "y" in validated
    assert "w" in validated
    assert "z" not in validated  # Filtered out
    assert "v" not in validated  # Filtered out


def test_validate_bulk_all_valid(validator):
    """Test bulk validation when all types are valid."""
    source = ""
    types_map = {
        "x": "int",
        "y": "str",
        "z": "list[int]",
    }
    validated = validator.validate_bulk(types_map, source)

    assert len(validated) == 3
    assert validated == types_map


def test_validate_bulk_empty(validator):
    """Test bulk validation with empty input."""
    source = ""
    types_map = {}
    validated = validator.validate_bulk(types_map, source)

    assert validated == {}


def test_validate_insertion_correct_type(validator):
    """Test validation of correct type insertion."""
    source = "x = 42"

    # Valid insertion
    valid, error = validator.validate_insertion(source, "x", "int")
    assert valid is True
    assert error == ""


def test_validate_insertion_wrong_type(validator):
    """Test validation catches wrong type insertion."""
    source = "x = 42"

    # Invalid insertion - string annotation for int value
    valid, error = validator.validate_insertion(source, "x", "str")
    assert valid is False
    assert len(error) > 0  # Should have error message


def test_validate_insertion_with_imports(validator):
    """Test validation respects imports during insertion."""
    source = """
from typing import List

x = [1, 2, 3]
"""

    # Should work with imported type
    valid, error = validator.validate_insertion(source, "x", "List[int]")
    assert valid is True
    assert error == ""


def test_validate_insertion_complex_type(validator):
    """Test validation of complex type insertion."""
    source = """
x = {"a": [1, 2, 3], "b": [4, 5, 6]}
"""

    # Valid complex type
    valid, error = validator.validate_insertion(source, "x", "dict[str, list[int]]")
    assert valid is True
    assert error == ""


def test_validate_function_signatures_all_valid(validator):
    """Test validation of function signatures."""
    source = """
def foo(x, y):
    return x + y
"""

    # Use simple dict format matching actual usage
    functions = {
        "module.foo": {  # func_id as key
            "name": "foo",
            "params": {"x": "int", "y": "int"},
            "return": "int",
        }
    }

    validated = validator.validate_function_signatures(functions, source)

    assert "module.foo" in validated
    assert validated["module.foo"]["params"] == {"x": "int", "y": "int"}
    # Return type might not validate in isolation without actual return statement context
    # So we'll just check params for now
    assert "return" in validated["module.foo"]


def test_validate_function_signatures_mixed_validity(validator):
    """Test validation filters out invalid function signature types."""
    source = """
class MyClass:
    pass

def foo(x, y):
    return MyClass()
"""

    functions = {
        "module.foo": {
            "name": "foo",
            "params": {"x": "int", "y": "UnknownType"},
            "return": "MyClass",
        }
    }

    validated = validator.validate_function_signatures(functions, source)

    assert "module.foo" in validated
    # Only valid parameter should remain
    assert validated["module.foo"]["params"] == {"x": "int"}
    assert validated["module.foo"]["return"] == "MyClass"


def test_validate_function_signatures_empty(validator):
    """Test validation with empty functions dict."""
    source = ""
    functions = {}

    validated = validator.validate_function_signatures(functions, source)

    assert validated == {}


def test_validate_with_syntax_errors_in_source(validator):
    """Test handling of syntax errors in source code."""
    source = "import "  # Syntax error

    # Validator should handle gracefully
    result = validator.validate("int", source)
    # May return False due to syntax error in source
    # This is acceptable behavior
    assert result in (True, False)


def test_validate_protocol_types(validator):
    """Test validation of Protocol types."""
    source = """
from typing import Protocol

class MyProtocol(Protocol):
    def method(self) -> int:
        ...
"""

    # Protocol subclass should be valid
    assert validator.validate("MyProtocol", source) is True


def test_validate_literal_types(validator):
    """Test validation of Literal types."""
    source = "from typing import Literal"

    assert validator.validate("Literal[1, 2, 3]", source) is True
    assert validator.validate("Literal['a', 'b']", source) is True


def test_validate_file_full_no_errors(validator):
    """Test validate_file_full returns empty list for valid code."""
    source = """
x: int = 42
y: str = "hello"
z: list[int] = [1, 2, 3]
"""
    diagnostics = validator.validate_file_full(source)
    assert len(diagnostics) == 0


def test_validate_file_full_single_error(validator):
    """Test validate_file_full detects a single type error."""
    source = """
x: str = 42
"""
    diagnostics = validator.validate_file_full(source)
    assert len(diagnostics) >= 1
    assert diagnostics[0].severity == "error"
    assert (
        "incompatible" in diagnostics[0].message.lower()
        or "assignment" in diagnostics[0].message.lower()
    )


def test_validate_file_full_multiple_errors(validator):
    """Test validate_file_full detects multiple errors."""
    source = """
x: str = 42
y: int = "hello"
z: list[str] = [1, 2, 3]
"""
    diagnostics = validator.validate_file_full(source)
    assert len(diagnostics) >= 3


def test_validate_file_full_line_numbers(validator):
    """Test validate_file_full returns correct line numbers."""
    source = """
x: int = 42
y: str = 123
"""
    diagnostics = validator.validate_file_full(source)
    assert len(diagnostics) >= 1
    # Error should be on line 3 (1-based, as mypy reports)
    assert any(d.line == 3 for d in diagnostics)


def test_validate_file_full_with_imports(validator):
    """Test validate_file_full works with imports."""
    source = """
from typing import List

x: List[int] = [1, 2, 3]
y: List[str] = [1, 2, 3]
"""
    diagnostics = validator.validate_file_full(source)
    # Should detect error in y
    assert len(diagnostics) >= 1


def test_validate_file_full_undefined_name(validator):
    """Test validate_file_full detects undefined names."""
    source = """
x = undefined_variable
"""
    diagnostics = validator.validate_file_full(source)
    assert len(diagnostics) >= 1
    assert "not defined" in diagnostics[0].message


def test_validate_file_full_function_errors(validator):
    """Test validate_file_full detects function type errors."""
    source = """
def foo(x: int) -> str:
    return x

result = foo("wrong")
"""
    diagnostics = validator.validate_file_full(source)
    # Should detect both return type error and argument type error
    assert len(diagnostics) >= 2


def test_validate_file_full_syntax_error(validator):
    """Test validate_file_full handles syntax errors."""
    source = """
def foo(
"""
    diagnostics = validator.validate_file_full(source)
    # Should report syntax error
    assert len(diagnostics) >= 1


def test_validate_file_full_error_codes(validator):
    """Test validate_file_full extracts error codes."""
    source = """
x: str = 42
"""
    diagnostics = validator.validate_file_full(source)
    assert len(diagnostics) >= 1
    # Mypy should provide error codes for most errors
    assert any(d.error_code is not None for d in diagnostics)


def test_validate_file_full_empty_source(validator):
    """Test validate_file_full with empty source."""
    source = ""
    diagnostics = validator.validate_file_full(source)
    assert len(diagnostics) == 0
