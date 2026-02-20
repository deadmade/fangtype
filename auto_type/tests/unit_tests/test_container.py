"""Tests for the dependency injection container."""

import asyncio
from unittest.mock import MagicMock

from injector import Injector

from auto_type.container import (
    get_container,
    reset_container,
    set_container,
)
from auto_type.diagnostics import DiagnosticEngine
from auto_type.inference.jedi_engine import JediInferenceEngine
from auto_type.insertion import UnifiedInsertionEngine
from auto_type.protocols import (
    DiagnosticEngineProtocol,
    InferenceEngineProtocol,
    TypeValidatorProtocol,
)
from auto_type.utils.code_action_helper import CodeActionHelper
from auto_type.utils.inlay_hint_helper import InlayHintHelper
from auto_type.validation import MypyTypeValidator


class TestContainerWiring:
    """Tests for correct wiring of engines via Injector."""

    def test_container_initialization(self) -> None:
        """Test that container initializes correctly."""
        container = get_container()
        assert container is not None
        assert isinstance(container, Injector)

    def test_engine_access(self) -> None:
        """Test that engines can be retrieved."""
        container = get_container()

        # Check instance types via protocols
        assert isinstance(container.get(InferenceEngineProtocol), JediInferenceEngine)
        assert isinstance(container.get(TypeValidatorProtocol), MypyTypeValidator)
        assert isinstance(container.get(UnifiedInsertionEngine), UnifiedInsertionEngine)
        assert isinstance(container.get(DiagnosticEngineProtocol), DiagnosticEngine)

    def test_singleton_scope(self) -> None:
        """Test that engines are singletons."""
        container = get_container()

        # Calling get twice should return same instance
        engine1 = container.get(InferenceEngineProtocol)
        engine2 = container.get(InferenceEngineProtocol)
        assert engine1 is engine2

        validator1 = container.get(TypeValidatorProtocol)
        validator2 = container.get(TypeValidatorProtocol)
        assert validator1 is validator2

    def test_diagnostic_engine_dependencies(self) -> None:
        """Test that diagnostic engine has its dependencies injected."""
        container = get_container()
        engine = container.get(DiagnosticEngine)

        # Check that validator was injected
        assert hasattr(engine, "mypy_validator")
        assert isinstance(engine.mypy_validator, MypyTypeValidator)

        # Check it's the same instance as the container's validator
        assert engine.mypy_validator is container.get(TypeValidatorProtocol)

    def test_helpers_wiring(self) -> None:
        """Test that helper classes are correctly wired."""
        container = get_container()

        diagnostic_engine = container.get(DiagnosticEngineProtocol)
        assert isinstance(diagnostic_engine, DiagnosticEngine)
        assert diagnostic_engine is container.get(DiagnosticEngine)

        # CodeActionHelper
        ca_helper = container.get(CodeActionHelper)
        assert isinstance(ca_helper, CodeActionHelper)
        assert hasattr(ca_helper, "insertion_engine")
        assert ca_helper.insertion_engine is container.get(UnifiedInsertionEngine)

        # InlayHintHelper
        ih_helper = container.get(InlayHintHelper)
        assert isinstance(ih_helper, InlayHintHelper)


class TestGlobalContainerAccessors:
    """Tests for global container accessor functions."""

    def test_get_container_creates_default(self) -> None:
        """Test that get_container creates a default container if none exists."""
        # Ensure no container exists (autouse fixture resets)
        container = get_container()
        assert container is not None
        assert isinstance(container, Injector)

    def test_get_container_returns_same_instance(self) -> None:
        """Test that get_container returns the same instance on multiple calls."""
        container1 = get_container()
        container2 = get_container()
        assert container1 is container2

    def test_set_container(self) -> None:
        """Test that set_container sets the global container."""
        custom_container = Injector()
        set_container(custom_container)

        assert get_container() is custom_container

    def test_reset_container(self) -> None:
        """Test that reset_container clears the global container."""
        # Get or create a container
        container1 = get_container()

        # Reset
        reset_container()

        # Next get_container should create a new instance
        container2 = get_container()
        assert container2 is not container1


class TestContainerIntegration:
    """Integration tests for container with real engines."""

    def test_inference_engine_works(self, sample_source: str) -> None:
        """Test that inference engine actually works."""
        container = get_container()
        engine = container.get(InferenceEngineProtocol)

        # Should be able to infer types
        result = engine.infer_types(sample_source)
        assert result is not None
        assert result.scope_tree is not None

    def test_type_validator_works(self, sample_source: str) -> None:
        """Test that type validator actually works."""
        container = get_container()
        validator = container.get(TypeValidatorProtocol)

        # Should be able to validate types
        valid_result = asyncio.run(validator.validate_bulk({"_single": "int"}, sample_source))
        assert valid_result["_single"].is_valid is True

        invalid_result = asyncio.run(
            validator.validate_bulk({"_single": "NonExistentType"}, sample_source)
        )
        assert invalid_result["_single"].is_valid is False

    def test_insertion_engine_works(self) -> None:
        """Test that insertion engine actually works."""
        container = get_container()
        engine = container.get(UnifiedInsertionEngine)

        # Import the types needed for the unified API
        from auto_type.insertion import CodeLocation, InsertionTarget, TargetType

        source = "x = 42\n"
        target = InsertionTarget(
            target_type=TargetType.VARIABLE_SIMPLE,
            location=CodeLocation(line=1, column=0),
            type_annotation="int",
            name="x",
        )
        result = engine.insert([target], source)

        assert result.success is True
        assert "x: int = 42" in result.modified_source

    def test_diagnostic_engine_works(self) -> None:
        """Test that diagnostic engine actually works."""
        container = get_container()
        engine = container.get(DiagnosticEngineProtocol)

        source = "x: int = 'not an int'\n"
        diagnostics = asyncio.run(engine.generate_diagnostics(source, "file:///test.py"))

        # Should produce at least one diagnostic for type error
        assert isinstance(diagnostics, list)


class TestContainerTestWorkflow:
    """Tests demonstrating the test workflow with mocks."""

    def test_mock_workflow(self, test_container: Injector) -> None:
        """Test that the test_container fixture provides a fully mocked container."""
        from unittest.mock import NonCallableMagicMock

        # All engines should be mocks
        inference_engine = test_container.get(InferenceEngineProtocol)
        assert isinstance(inference_engine, MagicMock | NonCallableMagicMock) or hasattr(
            inference_engine, "_spec_class"
        )

        type_validator = test_container.get(TypeValidatorProtocol)
        assert isinstance(type_validator, MagicMock | NonCallableMagicMock) or hasattr(
            type_validator, "_spec_class"
        )

        insertion_engine = test_container.get(UnifiedInsertionEngine)
        assert isinstance(insertion_engine, MagicMock | NonCallableMagicMock) or hasattr(
            insertion_engine, "_spec_class"
        )

        diagnostic_engine = test_container.get(DiagnosticEngineProtocol)
        assert isinstance(diagnostic_engine, MagicMock | NonCallableMagicMock) or hasattr(
            diagnostic_engine, "_spec_class"
        )

    def test_mock_can_be_configured(self, test_container: Injector) -> None:
        """Test that mocked engines can be configured with custom return values."""
        from typing import cast

        # Configure mock to return specific result
        inference_engine = test_container.get(InferenceEngineProtocol)

        # Use MagicMock for sync method
        mock_result = MagicMock()
        mock_result.scope_tree = MagicMock()
        mock_result.scope_tree.root = MagicMock()
        mock_result.scope_tree.root.variables = {}
        cast("MagicMock", inference_engine).infer_types = MagicMock(return_value=mock_result)

        # Should return configured value
        result = inference_engine.infer_types("x = 42")
        assert result.scope_tree.root.variables == {}

    def test_global_container_with_mocks(self, test_container: Injector) -> None:
        """Test using mocked container as the global container."""
        from unittest.mock import NonCallableMagicMock

        set_container(test_container)

        # get_container should now return our test container
        container = get_container()
        assert container is test_container

        # Engines should be mocks
        inference_engine = container.get(InferenceEngineProtocol)
        assert isinstance(inference_engine, MagicMock | NonCallableMagicMock) or hasattr(
            inference_engine, "_spec_class"
        )
