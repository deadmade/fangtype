"""Tests for type validator."""

import pytest

from auto_type.validation import TypeValidator


@pytest.fixture
def validator():
    """Create a TypeValidator instance."""
    return TypeValidator()


def test_validate_builtin_types(validator):
    """Test validation of Python builtin types."""
    assert validator.validate("int") is True
    assert validator.validate("str") is True
    assert validator.validate("bool") is True
    assert validator.validate("list") is True
    assert validator.validate("dict") is True
    assert validator.validate("set") is True
    assert validator.validate("tuple") is True
    assert validator.validate("float") is True
    assert validator.validate("bytes") is True
    assert validator.validate("None") is True


def test_validate_typing_module_types(validator):
    """Test validation of typing module types."""
    assert validator.validate("List") is True
    assert validator.validate("Dict") is True
    assert validator.validate("Optional") is True
    assert validator.validate("Union") is True
    assert validator.validate("Any") is True
    assert validator.validate("Callable") is True


def test_reject_unknown_type(validator):
    """Test rejection of unknown types."""
    assert validator.validate("UnknownType") is False
    assert validator.validate("MyClass") is False


def test_validate_with_scope(validator):
    """Test validation with custom scope."""
    scope = {"MyClass", "CustomType"}
    assert validator.validate("MyClass", scope) is True
    assert validator.validate("CustomType", scope) is True
    assert validator.validate("UnknownType", scope) is False


def test_is_valid_identifier(validator):
    """Test identifier validation."""
    assert validator.is_valid_identifier("int") is True
    assert validator.is_valid_identifier("MyClass") is True
    assert validator.is_valid_identifier("_private") is True
    assert validator.is_valid_identifier("123invalid") is False
    assert validator.is_valid_identifier("") is False
    assert validator.is_valid_identifier("class") is False  # keyword


def test_validate_generic_types(validator):
    """Test validation of generic type syntax."""
    # These should pass syntax check for builtins
    assert validator.validate("list[int]") is True
    assert validator.validate("dict[str, int]") is True
    assert validator.validate("set[str]") is True
    assert validator.validate("tuple[int, str]") is True


def test_extract_scope_from_imports(validator):
    """Test scope extraction from import statements."""
    source = """
import os
import sys
from typing import List, Dict
from pathlib import Path
"""
    scope = validator.extract_scope_names(source)
    assert "os" in scope
    assert "sys" in scope
    assert "List" in scope
    assert "Dict" in scope
    assert "Path" in scope


def test_extract_scope_from_class_definitions(validator):
    """Test scope extraction from class definitions."""
    source = """
class MyClass:
    pass

class AnotherClass:
    pass
"""
    scope = validator.extract_scope_names(source)
    assert "MyClass" in scope
    assert "AnotherClass" in scope


def test_extract_scope_with_import_aliases(validator):
    """Test scope extraction with import aliases."""
    source = """
import numpy as np
from typing import List as L
"""
    scope = validator.extract_scope_names(source)
    assert "np" in scope
    assert "L" in scope
    # Original names should not be in scope
    assert "numpy" not in scope
    assert "List" not in scope


def test_extract_scope_type_aliases(validator):
    """Test scope extraction of type aliases."""
    source = """
MyType = int
AnotherType = str
lowercase = int  # Should not be detected
"""
    scope = validator.extract_scope_names(source)
    assert "MyType" in scope
    assert "AnotherType" in scope
    # Lowercase variable names are not treated as types
    assert "lowercase" not in scope


def test_handle_syntax_error_in_scope_extraction(validator):
    """Test graceful handling of syntax errors."""
    source = "import "
    scope = validator.extract_scope_names(source)
    assert scope == set()


def test_validate_complex_source(validator):
    """Test validation with complex source containing multiple imports and classes."""
    source = """
from typing import List, Dict, Optional
import json

class MyClass:
    pass

class DataProcessor:
    pass

MyType = int
"""
    scope = validator.extract_scope_names(source)

    # Should validate imported types
    assert validator.validate("List", scope) is True
    assert validator.validate("Dict", scope) is True
    assert validator.validate("Optional", scope) is True

    # Should validate defined classes
    assert validator.validate("MyClass", scope) is True
    assert validator.validate("DataProcessor", scope) is True

    # Should validate type aliases
    assert validator.validate("MyType", scope) is True

    # Should validate imports
    assert validator.validate("json", scope) is True

    # Should reject unknown types
    assert validator.validate("UnknownClass", scope) is False


def test_empty_source(validator):
    """Test handling of empty source."""
    scope = validator.extract_scope_names("")
    assert scope == set()
    assert validator.validate("int") is True  # Builtins still work
