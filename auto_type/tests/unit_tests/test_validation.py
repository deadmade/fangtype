"""Tests for mypy-based type validator."""

import pytest

from auto_type.validation import MypyTypeValidator


@pytest.fixture
def validator():
    """Create a MypyTypeValidator instance."""
    return MypyTypeValidator()


async def test_validate_builtin_types(validator):
    """Test validation of Python builtin types."""
    source = ""
    assert await validator.validate("int", source) is True
    assert await validator.validate("str", source) is True
    assert await validator.validate("bool", source) is True
    assert await validator.validate("float", source) is True
    assert await validator.validate("bytes", source) is True
    assert await validator.validate("None", source) is True


async def test_validate_modern_generic_syntax(validator):
    """Test validation of modern generic syntax (Python 3.9+)."""
    source = ""
    assert await validator.validate("list[int]", source) is True
    assert await validator.validate("dict[str, int]", source) is True
    assert await validator.validate("set[str]", source) is True
    assert await validator.validate("tuple[int, str]", source) is True


async def test_validate_typing_module_types(validator):
    """Test validation with typing module imports."""
    source = "from typing import List, Dict, Optional, Union"
    assert await validator.validate("List[int]", source) is True
    assert await validator.validate("Dict[str, int]", source) is True
    assert await validator.validate("Optional[str]", source) is True
    assert await validator.validate("Union[int, str]", source) is True


async def test_reject_unknown_type(validator):
    """Test rejection of undefined types."""
    source = ""
    assert await validator.validate("UnknownType", source) is False
    assert await validator.validate("MyClass", source) is False


async def test_validate_with_custom_class(validator):
    """Test validation with custom class in source."""
    source = """
class MyClass:
    pass

class DataProcessor:
    pass
"""
    assert await validator.validate("MyClass", source) is True
    assert await validator.validate("DataProcessor", source) is True
    assert await validator.validate("UnknownClass", source) is False


async def test_validate_complex_generics(validator):
    """Test validation of complex generic types."""
    source = ""
    assert await validator.validate("dict[str, list[int]]", source) is True
    assert await validator.validate("list[dict[str, set[int]]]", source) is True
    assert await validator.validate("tuple[int, str, float]", source) is True


async def test_validate_union_types(validator):
    """Test validation of union types (PEP 604 syntax)."""
    source = ""
    assert await validator.validate("int | str", source) is True
    assert await validator.validate("list[int] | None", source) is True
    assert await validator.validate("str | int | float", source) is True


async def test_validate_callable_types(validator):
    """Test validation of callable types."""
    source = "from typing import Callable"
    assert await validator.validate("Callable[[int], str]", source) is True
    assert await validator.validate("Callable[[], None]", source) is True
    assert await validator.validate("Callable[[int, str], bool]", source) is True


async def test_validate_with_imports_and_aliases(validator):
    """Test validation respects imports and aliases."""
    source = """
from typing import List as L, Dict as D
"""
    assert await validator.validate("L[int]", source) is True
    assert await validator.validate("D[str, int]", source) is True


async def test_validate_rejects_unknown(validator):
    """Test that 'Unknown' is rejected."""
    source = ""
    assert await validator.validate("Unknown", source) is False


async def test_validate_bulk_filters_invalid(validator):
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
    validated = await validator.validate_bulk(types_map, source)

    assert "x" in validated
    assert "y" in validated
    assert "w" in validated
    assert "z" not in validated  # Filtered out
    assert "v" not in validated  # Filtered out


async def test_validate_bulk_all_valid(validator):
    """Test bulk validation when all types are valid."""
    source = ""
    types_map = {
        "x": "int",
        "y": "str",
        "z": "list[int]",
    }
    validated = await validator.validate_bulk(types_map, source)

    assert len(validated) == 3
    assert validated == types_map


async def test_validate_bulk_empty(validator):
    """Test bulk validation with empty input."""
    source = ""
    types_map: dict[str, str] = {}
    validated = await validator.validate_bulk(types_map, source)

    assert validated == {}


async def test_validate_insertion_correct_type(validator):
    """Test validation of correct type insertion."""
    source = "x = 42"

    # Valid insertion
    valid, error = await validator.validate_insertion(source, "x", "int")
    assert valid is True
    assert error == ""


async def test_validate_insertion_wrong_type(validator):
    """Test validation catches undefined type insertion.

    Note: validate_insertion() validates that the type annotation is syntactically
    valid and defined in scope, NOT that it's semantically correct for the value.
    Semantic validation (e.g., `str` for value `42`) is not performed.
    """
    source = "x = 42"

    # Valid type syntax - str is a valid type even if semantically wrong for value 42
    # The validator only checks if the type is defined, not semantic correctness
    valid, error = await validator.validate_insertion(source, "x", "str")
    assert valid is True
    assert error == ""

    # Invalid type - undefined type should fail
    valid, error = await validator.validate_insertion(source, "x", "UndefinedType")
    assert valid is False
    assert len(error) > 0  # Should have error message


async def test_validate_insertion_with_imports(validator):
    """Test validation respects imports during insertion."""
    source = """
from typing import List

x = [1, 2, 3]
"""

    # Should work with imported type
    valid, error = await validator.validate_insertion(source, "x", "List[int]")
    assert valid is True
    assert error == ""


async def test_validate_insertion_complex_type(validator):
    """Test validation of complex type insertion."""
    source = """
x = {"a": [1, 2, 3], "b": [4, 5, 6]}
"""

    # Valid complex type
    valid, error = await validator.validate_insertion(source, "x", "dict[str, list[int]]")
    assert valid is True
    assert error == ""


async def test_validate_with_syntax_errors_in_source(validator):
    """Test handling of syntax errors in source code."""
    source = "import "  # Syntax error

    # Validator should handle gracefully
    result = await validator.validate("int", source)
    # May return False due to syntax error in source
    # This is acceptable behavior
    assert result in (True, False)


async def test_validate_protocol_types(validator):
    """Test validation of Protocol types."""
    source = """
from typing import Protocol

class MyProtocol(Protocol):
    def method(self) -> int:
        ...
"""

    # Protocol subclass should be valid
    assert await validator.validate("MyProtocol", source) is True


async def test_validate_literal_types(validator):
    """Test validation of Literal types."""
    source = "from typing import Literal"

    assert await validator.validate("Literal[1, 2, 3]", source) is True
    assert await validator.validate("Literal['a', 'b']", source) is True


async def test_validate_file_full_no_errors(validator):
    """Test validate_file_full returns empty list for valid code."""
    source = """
x: int = 42
y: str = "hello"
z: list[int] = [1, 2, 3]
"""
    diagnostics = await validator.validate_file_full(source)
    assert len(diagnostics) == 0


async def test_validate_file_full_single_error(validator):
    """Test validate_file_full detects a single type error."""
    source = """
x: str = 42
"""
    diagnostics = await validator.validate_file_full(source)
    assert len(diagnostics) >= 1
    assert diagnostics[0].severity == "error"
    assert (
        "incompatible" in diagnostics[0].message.lower()
        or "assignment" in diagnostics[0].message.lower()
    )


async def test_validate_file_full_multiple_errors(validator):
    """Test validate_file_full detects multiple errors."""
    source = """
x: str = 42
y: int = "hello"
z: list[str] = [1, 2, 3]
"""
    diagnostics = await validator.validate_file_full(source)
    assert len(diagnostics) >= 3


async def test_validate_file_full_line_numbers(validator):
    """Test validate_file_full returns correct line numbers."""
    source = """
x: int = 42
y: str = 123
"""
    diagnostics = await validator.validate_file_full(source)
    assert len(diagnostics) >= 1
    # Error should be on line 3 (1-based, as mypy reports)
    assert any(d.line == 3 for d in diagnostics)


async def test_validate_file_full_with_imports(validator):
    """Test validate_file_full works with imports."""
    source = """
from typing import List

x: List[int] = [1, 2, 3]
y: List[str] = [1, 2, 3]
"""
    diagnostics = await validator.validate_file_full(source)
    # Should detect error in y
    assert len(diagnostics) >= 1


async def test_validate_file_full_undefined_name(validator):
    """Test validate_file_full detects undefined names."""
    source = """
x = undefined_variable
"""
    diagnostics = await validator.validate_file_full(source)
    assert len(diagnostics) >= 1
    assert "not defined" in diagnostics[0].message


async def test_validate_file_full_function_errors(validator):
    """Test validate_file_full detects function type errors."""
    source = """
def foo(x: int) -> str:
    return x

result = foo("wrong")
"""
    diagnostics = await validator.validate_file_full(source)
    # Should detect both return type error and argument type error
    assert len(diagnostics) >= 2


async def test_validate_file_full_syntax_error(validator):
    """Test validate_file_full handles syntax errors."""
    source = """
def foo(
"""
    diagnostics = await validator.validate_file_full(source)
    # Should report syntax error
    assert len(diagnostics) >= 1


async def test_validate_file_full_error_codes(validator):
    """Test validate_file_full extracts error codes."""
    source = """
x: str = 42
"""
    diagnostics = await validator.validate_file_full(source)
    assert len(diagnostics) >= 1
    # Mypy should provide error codes for most errors
    assert any(d.error_code is not None for d in diagnostics)


async def test_validate_file_full_empty_source(validator):
    """Test validate_file_full with empty source."""
    source = ""
    diagnostics = await validator.validate_file_full(source)
    assert len(diagnostics) == 0


async def test_validate_bulk_with_dotted_keys(validator):
    """Test that validate_bulk() handles keys with dots (e.g., scope_id.var.name).

    This test verifies the fix for ghost text (inlay hints) not appearing in VSCode.
    The server creates validation keys like "module.var.x" which contain dots.
    These dots must be sanitized to underscores before creating test code,
    otherwise mypy rejects them as invalid Python syntax.
    """
    types_map = {
        "module.var.x": "int",
        "module.var.name": "str",
        "func1.param.value": "float",
        "func1.return": "bool",
        "nested.scope.var.items": "list[int]",
    }

    source = ""

    result = await validator.validate_bulk(types_map, source)

    assert "module.var.x" in result
    assert result["module.var.x"] == "int"
    assert "module.var.name" in result
    assert result["module.var.name"] == "str"
    assert "func1.param.value" in result
    assert result["func1.param.value"] == "float"
    assert "func1.return" in result
    assert result["func1.return"] == "bool"
    assert "nested.scope.var.items" in result
    assert result["nested.scope.var.items"] == "list[int]"
