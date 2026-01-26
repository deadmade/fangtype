"""Pytest fixtures for unit tests.

This module provides reusable test fixtures for mocking the engine components
and managing the global container during tests.
"""

from typing import Any
from unittest.mock import MagicMock, create_autospec

import pytest
from injector import Injector, Module, singleton

from auto_type.container import reset_container
from auto_type.diagnostics import DiagnosticEngine
from auto_type.inference import JediInferenceEngine
from auto_type.insertion import UnifiedInsertionEngine
from auto_type.protocols import (
    DiagnosticEngineProtocol,
    InferenceEngineProtocol,
    TypeValidatorProtocol,
)
from auto_type.validation import MypyTypeValidator


@pytest.fixture
def mock_inference_engine() -> MagicMock:
    """Create a mock inference engine.

    Returns:
        MagicMock configured with InferenceEngineProtocol spec
    """
    mock = create_autospec(InferenceEngineProtocol, instance=True)

    # Set up default return values
    mock_scope_tree = MagicMock()
    mock_scope_tree.scopes_by_id = {}
    mock_scope_tree.root = MagicMock()
    mock_scope_tree.root.variables = {}

    mock_result = MagicMock()
    mock_result.scope_tree = mock_scope_tree
    mock_result.get_all_insertable_types.return_value = {
        "module_vars": {},
        "functions": {},
    }

    mock.infer_types.return_value = mock_result
    mock.infer_variable_types.return_value = {}
    mock.infer_expression_type.return_value = None

    return mock


@pytest.fixture
def mock_type_validator() -> MagicMock:
    """Create a mock type validator.

    Returns:
        MagicMock configured with TypeValidatorProtocol spec
    """
    mock = create_autospec(TypeValidatorProtocol, instance=True)

    # Set up default return values
    mock.validate.return_value = True
    mock.validate_bulk.return_value = {}
    mock.validate_insertion.return_value = (True, "")
    mock.validate_file_full.return_value = []

    return mock


@pytest.fixture
def mock_insertion_engine() -> MagicMock:
    """Create a mock unified insertion engine.

    Returns:
        MagicMock configured with UnifiedInsertionEngine spec
    """
    mock = create_autospec(UnifiedInsertionEngine, instance=True)

    # Set up default return values for the unified API
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.modified_source = "modified"  # Default to "modified" for tests
    mock_result.inserted_count = 1
    mock_result.error_message = None
    mock_result.details = {}
    mock_result.failed_targets = []

    mock.insert.return_value = mock_result
    mock.insert_variable_annotation.return_value = mock_result
    mock.insert_function_parameter_annotation.return_value = mock_result
    mock.insert_function_return_annotation.return_value = mock_result
    mock.preview_insertions.return_value = {
        "success": True,
        "total_plans": 0,
        "plans_by_strategy": {},
        "plan_details": [],
    }

    return mock


@pytest.fixture
def mock_diagnostic_engine() -> MagicMock:
    """Create a mock diagnostic engine.

    Returns:
        MagicMock configured with DiagnosticEngineProtocol spec
    """
    mock = create_autospec(DiagnosticEngineProtocol, instance=True)

    # Set up default return values
    mock.generate_diagnostics.return_value = []

    return mock


@pytest.fixture
def test_container(
    mock_inference_engine: MagicMock,
    mock_type_validator: MagicMock,
    mock_insertion_engine: MagicMock,
    mock_diagnostic_engine: MagicMock,
) -> Injector:
    """Create a test container with all engines mocked.

    Args:
        mock_inference_engine: Mock inference engine fixture
        mock_type_validator: Mock type validator fixture
        mock_insertion_engine: Mock insertion engine fixture
        mock_diagnostic_engine: Mock diagnostic engine fixture

    Returns:
        Injector with all mocked engines
    """

    class TestModule(Module):
        def configure(self, binder):
            binder.bind(InferenceEngineProtocol, to=mock_inference_engine, scope=singleton)
            binder.bind(TypeValidatorProtocol, to=mock_type_validator, scope=singleton)
            binder.bind(UnifiedInsertionEngine, to=mock_insertion_engine, scope=singleton)
            binder.bind(DiagnosticEngineProtocol, to=mock_diagnostic_engine, scope=singleton)

            # Also bind concrete classes to mocks just in case
            binder.bind(JediInferenceEngine, to=mock_inference_engine, scope=singleton)
            binder.bind(MypyTypeValidator, to=mock_type_validator, scope=singleton)
            binder.bind(DiagnosticEngine, to=mock_diagnostic_engine, scope=singleton)

    injector = Injector([TestModule()])
    return injector


@pytest.fixture(autouse=True)
def reset_global_container() -> Any:
    """Reset the global container before and after each test.

    This fixture runs automatically for all tests to ensure test isolation.
    """
    reset_container()
    yield
    reset_container()


@pytest.fixture
def sample_source() -> str:
    """Provide sample Python source code for tests.

    Returns:
        Sample Python source code string
    """
    return '''"""Sample module for testing."""

x = 42
name = "hello"


def greet(name):
    return f"Hello, {name}!"


class Calculator:
    def add(self, a, b):
        return a + b
'''


@pytest.fixture
def sample_typed_source() -> str:
    """Provide sample Python source code with type annotations.

    Returns:
        Sample Python source code with types
    """
    return '''"""Sample module with types."""

x: int = 42
name: str = "hello"


def greet(name: str) -> str:
    return f"Hello, {name}!"


class Calculator:
    def add(self, a: int, b: int) -> int:
        return a + b
'''
