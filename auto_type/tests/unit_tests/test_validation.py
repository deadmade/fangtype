"""Tests for mypy-based type validator."""

from unittest.mock import AsyncMock, patch

import pytest

from auto_type.validation import mypy_validator as mypy_validator_module
from auto_type.validation import MypyTypeValidator
from auto_type.validation.mypy_validator import TypeValidationResult


@pytest.fixture
def validator():
    """Create a MypyTypeValidator instance."""
    return MypyTypeValidator()


async def _validate_single(validator: MypyTypeValidator, type_str: str, source: str) -> bool:
    """Validate one type via the bulk validator API."""
    result = await validator.validate_bulk({"_single": type_str}, source)
    single_result = result.get("_single")
    return bool(single_result and single_result.is_valid)


async def test_validate_builtin_types(validator):
    """Test validation of Python builtin types."""
    source = ""
    assert await _validate_single(validator, "int", source) is True
    assert await _validate_single(validator, "str", source) is True
    assert await _validate_single(validator, "bool", source) is True
    assert await _validate_single(validator, "float", source) is True
    assert await _validate_single(validator, "bytes", source) is True
    assert await _validate_single(validator, "None", source) is True


async def test_validate_modern_generic_syntax(validator):
    """Test validation of modern generic syntax (Python 3.9+)."""
    source = ""
    assert await _validate_single(validator, "list[int]", source) is True
    assert await _validate_single(validator, "dict[str, int]", source) is True
    assert await _validate_single(validator, "set[str]", source) is True
    assert await _validate_single(validator, "tuple[int, str]", source) is True


async def test_validate_typing_module_types(validator):
    """Test validation with typing module imports."""
    source = "from typing import List, Dict, Optional, Union"
    assert await _validate_single(validator, "List[int]", source) is True
    assert await _validate_single(validator, "Dict[str, int]", source) is True
    assert await _validate_single(validator, "Optional[str]", source) is True
    assert await _validate_single(validator, "Union[int, str]", source) is True


async def test_reject_unknown_type(validator):
    """Test rejection of undefined types."""
    source = ""
    assert await _validate_single(validator, "UnknownType", source) is False
    assert await _validate_single(validator, "MyClass", source) is False


async def test_validate_with_custom_class(validator):
    """Test validation with custom class in source."""
    source = """
class MyClass:
    pass

class DataProcessor:
    pass
"""
    assert await _validate_single(validator, "MyClass", source) is True
    assert await _validate_single(validator, "DataProcessor", source) is True
    assert await _validate_single(validator, "UnknownClass", source) is False


async def test_validate_complex_generics(validator):
    """Test validation of complex generic types."""
    source = ""
    assert await _validate_single(validator, "dict[str, list[int]]", source) is True
    assert await _validate_single(validator, "list[dict[str, set[int]]]", source) is True
    assert await _validate_single(validator, "tuple[int, str, float]", source) is True


async def test_validate_union_types(validator):
    """Test validation of union types (PEP 604 syntax)."""
    source = ""
    assert await _validate_single(validator, "int | str", source) is True
    assert await _validate_single(validator, "list[int] | None", source) is True
    assert await _validate_single(validator, "str | int | float", source) is True


async def test_validate_callable_types(validator):
    """Test validation of callable types."""
    source = "from typing import Callable"
    assert await _validate_single(validator, "Callable[[int], str]", source) is True
    assert await _validate_single(validator, "Callable[[], None]", source) is True
    assert await _validate_single(validator, "Callable[[int, str], bool]", source) is True


async def test_validate_with_imports_and_aliases(validator):
    """Test validation respects imports and aliases."""
    source = """
from typing import List as L, Dict as D
"""
    assert await _validate_single(validator, "L[int]", source) is True
    assert await _validate_single(validator, "D[str, int]", source) is True


async def test_validate_rejects_unknown(validator):
    """Test that 'Unknown' is rejected."""
    source = ""
    assert await _validate_single(validator, "Unknown", source) is False


async def test_validate_bulk_returns_all_with_validation_status(validator):
    """Test bulk validation returns all types with validation status."""
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

    # All types should be returned
    assert "x" in validated
    assert "y" in validated
    assert "z" in validated
    assert "w" in validated
    assert "v" in validated

    # Check validation status
    assert validated["x"].is_valid is True
    assert validated["y"].is_valid is True
    assert validated["w"].is_valid is True
    assert validated["z"].is_valid is False  # Invalid type
    assert validated["v"].is_valid is False  # Invalid type

    # Check type strings are preserved
    assert validated["x"].type_str == "int"
    assert validated["z"].type_str == "UnknownType"


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
    # Check all are valid MypyDiagnostic objects
    assert validated["x"].is_valid is True
    assert validated["x"].type_str == "int"
    assert validated["y"].is_valid is True
    assert validated["y"].type_str == "str"
    assert validated["z"].is_valid is True
    assert validated["z"].type_str == "list[int]"


async def test_validate_bulk_empty(validator):
    """Test bulk validation with empty input."""
    source = ""
    types_map: dict[str, str] = {}
    validated = await validator.validate_bulk(types_map, source)

    assert validated == {}


async def test_validate_with_syntax_errors_in_source(validator):
    """Test handling of syntax errors in source code."""
    source = "import "  # Syntax error

    # Validator should handle gracefully
    result = await _validate_single(validator, "int", source)
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
    assert await _validate_single(validator, "MyProtocol", source) is True


async def test_validate_literal_types(validator):
    """Test validation of Literal types."""
    source = "from typing import Literal"

    assert await _validate_single(validator, "Literal[1, 2, 3]", source) is True
    assert await _validate_single(validator, "Literal['a', 'b']", source) is True


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

    # All keys should be present with MypyDiagnostic objects
    assert "module.var.x" in result
    assert result["module.var.x"].is_valid is True
    assert result["module.var.x"].type_str == "int"
    assert "module.var.name" in result
    assert result["module.var.name"].is_valid is True
    assert result["module.var.name"].type_str == "str"
    assert "func1.param.value" in result
    assert result["func1.param.value"].is_valid is True
    assert result["func1.param.value"].type_str == "float"
    assert "func1.return" in result
    assert result["func1.return"].is_valid is True
    assert result["func1.return"].type_str == "bool"
    assert "nested.scope.var.items" in result
    assert result["nested.scope.var.items"].is_valid is True
    assert result["nested.scope.var.items"].type_str == "list[int]"


async def test_validate_file_full_offloads_only_mypy_run(validator):
    """Test validate_file_full wraps only mypy execution in asyncio.to_thread."""
    source = "x: int = 1"

    with patch(
        "auto_type.validation.mypy_validator.asyncio.to_thread",
        new_callable=AsyncMock,
    ) as mock_to_thread:
        mock_to_thread.return_value = []

        diagnostics = await validator.validate_file_full(source)

    assert diagnostics == []
    mock_to_thread.assert_awaited_once()
    called_callable, called_args = mock_to_thread.await_args.args
    assert called_callable.__func__ is validator._validate_file_full_sync.__func__
    assert called_args == source


async def test_validate_bulk_offloads_only_mypy_run(validator):
    """Test validate_bulk wraps only mypy execution in asyncio.to_thread."""
    source = ""
    types_map = {"x": "int"}

    with patch(
        "auto_type.validation.mypy_validator.asyncio.to_thread",
        new_callable=AsyncMock,
    ) as mock_to_thread:
        mock_to_thread.return_value = {"x": TypeValidationResult(type_str="int", is_valid=True)}

        result = await validator.validate_bulk(types_map, source)

    assert "x" in result
    assert result["x"].is_valid is True
    mock_to_thread.assert_awaited_once()
    called_callable, types_arg, source_arg = mock_to_thread.await_args.args
    assert called_callable.__func__ is validator._validate_bulk_sync.__func__
    assert types_arg == types_map
    assert source_arg == source
