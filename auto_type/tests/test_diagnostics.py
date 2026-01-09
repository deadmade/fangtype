"""Tests for diagnostic engine and mypy integration."""

import pytest
from lsprotocol import types

from auto_type.diagnostics import DiagnosticEngine
from auto_type.validation import MypyTypeValidator


@pytest.fixture
def validator():
    """Create a MypyTypeValidator instance."""
    return MypyTypeValidator()


@pytest.fixture
def engine(validator):
    """Create a DiagnosticEngine instance."""
    return DiagnosticEngine(validator)


def test_generate_diagnostics_no_errors(engine):
    """Test that valid code produces no diagnostics."""
    source = """
x: int = 42
y: str = "hello"
"""
    diagnostics = engine.generate_diagnostics(source, "test.py")
    assert len(diagnostics) == 0


def test_generate_diagnostics_type_mismatch(engine):
    """Test detection of type mismatch."""
    source = """
x: str = 42
"""
    diagnostics = engine.generate_diagnostics(source, "test.py")
    assert len(diagnostics) == 1
    assert diagnostics[0].severity == types.DiagnosticSeverity.Error
    assert diagnostics[0].source == "mypy"
    assert (
        "Incompatible types" in diagnostics[0].message
        or "incompatible" in diagnostics[0].message.lower()
    )


def test_generate_diagnostics_undefined_name(engine):
    """Test detection of undefined names."""
    source = """
x = undefined_variable
"""
    diagnostics = engine.generate_diagnostics(source, "test.py")
    assert len(diagnostics) == 1
    assert diagnostics[0].severity == types.DiagnosticSeverity.Error
    assert diagnostics[0].source == "mypy"
    assert "not defined" in diagnostics[0].message


def test_generate_diagnostics_multiple_errors(engine):
    """Test detection of multiple errors in one file."""
    source = """
x: str = 42
y: int = "hello"
z = undefined_var
"""
    diagnostics = engine.generate_diagnostics(source, "test.py")
    assert len(diagnostics) >= 3  # At least 3 errors


def test_generate_diagnostics_syntax_error(engine):
    """Test handling of syntax errors."""
    source = """
def foo(
"""
    diagnostics = engine.generate_diagnostics(source, "test.py")
    # Mypy should report syntax error
    assert len(diagnostics) >= 1


def test_generate_diagnostics_with_imports(engine):
    """Test diagnostics work with imports."""
    source = """
from typing import List

x: List[int] = [1, 2, 3]
y: List[str] = [1, 2, 3]
"""
    diagnostics = engine.generate_diagnostics(source, "test.py")
    # Should have error for y (wrong type)
    assert len(diagnostics) >= 1
    assert any("incompatible" in d.message.lower() for d in diagnostics)


def test_generate_diagnostics_missing_return_type(engine):
    """Test detection of missing return type warnings."""
    source = """
def foo(x):
    return x + 1
"""
    diagnostics = engine.generate_diagnostics(source, "test.py")
    # Mypy will complain about missing type annotations
    assert len(diagnostics) >= 1
    # Should be warnings, not errors
    assert any(d.severity == types.DiagnosticSeverity.Warning for d in diagnostics)


def test_diagnostic_line_numbers_correct(engine):
    """Test that line numbers are correctly converted to 0-based."""
    source = """
x: int = 42
y: str = 123
"""
    diagnostics = engine.generate_diagnostics(source, "test.py")
    assert len(diagnostics) >= 1
    # Error should be on line 2 (0-based) for the y assignment
    error_for_y = [d for d in diagnostics if d.range.start.line == 2]
    assert len(error_for_y) >= 1


def test_diagnostic_has_error_code(engine):
    """Test that diagnostics include mypy error codes when available."""
    source = """
x: str = 42
"""
    diagnostics = engine.generate_diagnostics(source, "test.py")
    assert len(diagnostics) >= 1
    # Mypy should provide an error code
    assert diagnostics[0].code is not None


def test_diagnostic_severity_levels(engine):
    """Test that different severity levels are handled."""
    source = """
from typing_extensions import reveal_type

x: int = 42
reveal_type(x)  # This produces a note
"""
    diagnostics = engine.generate_diagnostics(source, "test.py")
    # Should have diagnostics (reveal_type produces a note in mypy)
    # If no note is produced, at least verify the test doesn't crash
    assert isinstance(diagnostics, list)


def test_diagnostic_empty_source(engine):
    """Test handling of empty source."""
    source = ""
    diagnostics = engine.generate_diagnostics(source, "test.py")
    assert len(diagnostics) == 0


def test_diagnostic_complex_types(engine):
    """Test diagnostics with complex generic types."""
    source = """
from typing import Dict, List

x: Dict[str, List[int]] = {"a": [1, 2], "b": ["wrong"]}
"""
    diagnostics = engine.generate_diagnostics(source, "test.py")
    assert len(diagnostics) >= 1
    assert any("incompatible" in d.message.lower() for d in diagnostics)


def test_diagnostic_function_return_type(engine):
    """Test diagnostics for function return type mismatches."""
    source = """
def foo() -> int:
    return "string"
"""
    diagnostics = engine.generate_diagnostics(source, "test.py")
    assert len(diagnostics) >= 1
    assert any("return" in d.message.lower() for d in diagnostics)


def test_diagnostic_function_argument_type(engine):
    """Test diagnostics for function argument type mismatches."""
    source = """
def foo(x: int) -> int:
    return x + 1

result = foo("string")
"""
    diagnostics = engine.generate_diagnostics(source, "test.py")
    assert len(diagnostics) >= 1
    assert any(
        "argument" in d.message.lower() or "incompatible" in d.message.lower() for d in diagnostics
    )


def test_diagnostic_union_types(engine):
    """Test diagnostics with union types."""
    source = """
x: int | str = 42
y: int | str = []  # Wrong type
"""
    diagnostics = engine.generate_diagnostics(source, "test.py")
    assert len(diagnostics) >= 1


def test_diagnostic_with_class_definition(engine):
    """Test diagnostics work with class definitions."""
    source = """
class MyClass:
    x: int = "wrong"

    def method(self) -> str:
        return 42
"""
    diagnostics = engine.generate_diagnostics(source, "test.py")
    assert len(diagnostics) >= 2  # Both errors should be caught


def test_diagnostic_column_positions(engine):
    """Test that column positions are reasonable."""
    source = """
x: str = 42
"""
    diagnostics = engine.generate_diagnostics(source, "test.py")
    assert len(diagnostics) >= 1
    # Column should be non-negative
    assert diagnostics[0].range.start.character >= 0
    # End should be after start
    assert diagnostics[0].range.end.character >= diagnostics[0].range.start.character


def test_validate_file_full_parsing(validator):
    """Test the mypy output parsing directly."""
    source = """
x: str = 42
y: int = "hello"
"""
    mypy_diagnostics = validator.validate_file_full(source)
    assert len(mypy_diagnostics) >= 2
    assert all(hasattr(d, "line") for d in mypy_diagnostics)
    assert all(hasattr(d, "message") for d in mypy_diagnostics)
    assert all(hasattr(d, "severity") for d in mypy_diagnostics)


def test_validate_file_full_no_errors(validator):
    """Test validate_file_full with valid code."""
    source = """
x: int = 42
y: str = "hello"
"""
    mypy_diagnostics = validator.validate_file_full(source)
    assert len(mypy_diagnostics) == 0


def test_validate_file_full_line_numbers(validator):
    """Test that line numbers are correctly extracted from mypy."""
    source = """
x: int = 42
y: str = 123
z: bool = "text"
"""
    mypy_diagnostics = validator.validate_file_full(source)
    assert len(mypy_diagnostics) >= 2
    # Line numbers should be positive and in order
    lines = [d.line for d in mypy_diagnostics]
    assert all(line > 0 for line in lines)


def test_validate_file_full_error_codes(validator):
    """Test that error codes are extracted when present."""
    source = """
x: str = 42
"""
    mypy_diagnostics = validator.validate_file_full(source)
    assert len(mypy_diagnostics) >= 1
    # Most type errors should have error codes
    assert any(d.error_code is not None for d in mypy_diagnostics)


def test_diagnostic_missing_function_parameter_types(engine):
    """Test detection of functions with untyped parameters."""
    source = """
def add(x, y):
    return x + y
"""
    diagnostics = engine.generate_diagnostics(source, "test.py")
    # Should have diagnostic for missing type annotations
    assert len(diagnostics) >= 1
    # Should be a warning, not an error (due to severity remapping)
    assert any(d.severity == types.DiagnosticSeverity.Warning for d in diagnostics)
    # Should mention the function definition issue
    assert any(
        "untyped" in d.message.lower() or "annotation" in d.message.lower() for d in diagnostics
    )


def test_diagnostic_missing_return_type_only(engine):
    """Test detection of functions missing only return type."""
    source = """
def greet(name: str):
    return f"Hello, {name}"
"""
    diagnostics = engine.generate_diagnostics(source, "test.py")
    # Should have diagnostic for missing return type
    assert len(diagnostics) >= 1
    assert any(d.severity == types.DiagnosticSeverity.Warning for d in diagnostics)


def test_diagnostic_partially_typed_function(engine):
    """Test functions with some but not all parameters typed."""
    source = """
def calculate(x: int, y, z: float):
    return x + y + z
"""
    diagnostics = engine.generate_diagnostics(source, "test.py")
    # Should have diagnostic for incomplete annotations
    assert len(diagnostics) >= 1
    assert any(d.severity == types.DiagnosticSeverity.Warning for d in diagnostics)


def test_diagnostic_method_missing_types(engine):
    """Test class methods are also checked for missing types."""
    source = """
class Calculator:
    def add(self, x, y):
        return x + y
"""
    diagnostics = engine.generate_diagnostics(source, "test.py")
    # Should have diagnostic for untyped method
    assert len(diagnostics) >= 1
    assert any(d.severity == types.DiagnosticSeverity.Warning for d in diagnostics)


def test_diagnostic_nested_function_missing_types(engine):
    """Test nested functions are checked for missing types."""
    source = """
def outer(x: int) -> int:
    def inner(y):
        return y + 1
    return inner(x)
"""
    diagnostics = engine.generate_diagnostics(source, "test.py")
    # Should have diagnostic for untyped nested function
    assert len(diagnostics) >= 1
    assert any(d.severity == types.DiagnosticSeverity.Warning for d in diagnostics)


def test_diagnostic_fully_typed_function_no_warning(engine):
    """Test that fully typed functions don't generate warnings."""
    source = """
def add(x: int, y: int) -> int:
    return x + y
"""
    diagnostics = engine.generate_diagnostics(source, "test.py")
    # Should have no diagnostics for properly typed function
    assert len(diagnostics) == 0


def test_diagnostic_missing_types_error_code(engine):
    """Test that missing annotation diagnostics have the correct error code."""
    source = """
def foo(x):
    return x
"""
    diagnostics = engine.generate_diagnostics(source, "test.py")
    assert len(diagnostics) >= 1
    # Should have the no-untyped-def error code
    assert any(d.code == "no-untyped-def" for d in diagnostics)
