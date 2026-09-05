"""Reusable unit-test fixtures for mocking engine components and building a FangtypeServer."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, create_autospec

import pytest
from injector import Injector, Module, singleton

from fangtype.diagnostics import DiagnosticEngine
from fangtype.inference.jedi.engine import JediInferenceEngine
from fangtype.insertion import InsertionEngine
from fangtype.protocols import (
    DiagnosticEngineProtocol,
    InferenceEngineProtocol,
    TypeValidatorProtocol,
)
from fangtype.server import FangtypeServer
from fangtype.utils.settings import Settings
from fangtype.validation import MypyTypeValidator


def make_test_server(**overrides: Any) -> FangtypeServer:
    """Build a FangtypeServer with mock deps by default; keyword overrides substitute specifics."""
    deps: dict[str, Any] = {
        "workflow": MagicMock(),
        "diagnostics": MagicMock(),
        "code_action_helper": MagicMock(),
        "inlay_hints_helper": MagicMock(),
        "settings": Settings(),
        "validator": MagicMock(),
        "document_cache": MagicMock(),
    }
    deps.update(overrides)
    server = FangtypeServer(**deps)
    # Stub the outbound client REQUEST so transport-less tests don't hang; __setattr__ dodges B010.
    object.__setattr__(server, "workspace_inlay_hint_refresh_async", AsyncMock())
    return server


@pytest.fixture
def lsp_server() -> FangtypeServer:
    """A fresh server per test with all dependencies mocked."""
    return make_test_server()


@pytest.fixture
def mock_inference_engine() -> MagicMock:
    """Mock inference engine autospec'd against InferenceEngineProtocol."""
    mock = create_autospec(InferenceEngineProtocol, instance=True)

    # Set up default return values
    mock_scope_tree = MagicMock()
    mock_scope_tree.scopes_by_id = {}
    mock_scope_tree.root = MagicMock()
    mock_scope_tree.root.variables = {}

    mock_result = MagicMock()
    mock_result.scope_tree = mock_scope_tree

    mock.infer_types.return_value = mock_result

    return mock


@pytest.fixture
def mock_type_validator() -> MagicMock:
    """Mock type validator autospec'd against TypeValidatorProtocol."""
    mock = create_autospec(TypeValidatorProtocol, instance=True)

    # Set up default return values
    mock.validate_file_full.return_value = []

    return mock


@pytest.fixture
def mock_insertion_engine() -> MagicMock:
    """Mock unified insertion engine autospec'd against InsertionEngine."""
    mock = create_autospec(InsertionEngine, instance=True)

    # Set up default return values for the unified API
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.modified_source = "modified"  # Default to "modified" for tests
    mock_result.inserted_count = 1
    mock_result.error_message = None
    mock_result.details = {}
    mock_result.failed_targets = []

    mock.insert.return_value = mock_result

    return mock


@pytest.fixture
def mock_diagnostic_engine() -> MagicMock:
    """Mock diagnostic engine autospec'd against DiagnosticEngineProtocol."""
    mock = create_autospec(DiagnosticEngineProtocol, instance=True)

    # Set up default return values
    mock.generate_diagnostics.return_value = []
    mock.run_diagnostics.return_value = None
    mock.schedule_diagnostics.return_value = None

    return mock


@pytest.fixture
def test_container(
    mock_inference_engine: MagicMock,
    mock_type_validator: MagicMock,
    mock_insertion_engine: MagicMock,
    mock_diagnostic_engine: MagicMock,
) -> Injector:
    """Injector binding all engine protocols and concrete classes to the mock fixtures."""

    class TestModule(Module):
        def configure(self, binder):
            binder.bind(InferenceEngineProtocol, to=mock_inference_engine, scope=singleton)
            binder.bind(TypeValidatorProtocol, to=mock_type_validator, scope=singleton)
            binder.bind(InsertionEngine, to=mock_insertion_engine, scope=singleton)
            binder.bind(DiagnosticEngineProtocol, to=mock_diagnostic_engine, scope=singleton)

            # Also bind concrete classes to mocks just in case
            binder.bind(JediInferenceEngine, to=mock_inference_engine, scope=singleton)
            binder.bind(MypyTypeValidator, to=mock_type_validator, scope=singleton)
            binder.bind(DiagnosticEngine, to=mock_diagnostic_engine, scope=singleton)

    injector = Injector([TestModule()])
    return injector


@pytest.fixture
def engine() -> JediInferenceEngine:
    """A fresh Jedi engine per test — function-scoped so per-test caching stays isolated."""
    return JediInferenceEngine(Settings())


@pytest.fixture
def sample_source() -> str:
    """Provide sample Python source code for tests."""
    return '''"""Sample module for testing."""

x = 42
name = "hello"


def greet(name):
    return f"Hello, {name}!"


class Calculator:
    def add(self, a, b):
        return a + b
'''
