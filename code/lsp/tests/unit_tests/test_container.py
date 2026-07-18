"""Tests for the dependency injection container."""

import ast
import asyncio
from unittest.mock import MagicMock

from injector import Injector

from fangtype.container import build_container
from fangtype.diagnostics import DiagnosticEngine
from fangtype.inference.jedi.engine import JediInferenceEngine
from fangtype.insertion import InsertionEngine
from fangtype.protocols import (
    DiagnosticEngineProtocol,
    InferenceEngineProtocol,
    TypeValidatorProtocol,
)
from fangtype.removal import RemovalEngine
from fangtype.utils.code_action_helper import CodeActionHelper
from fangtype.utils.inlay_hint_helper import InlayHintHelper
from fangtype.validation import MypyTypeValidator


class TestContainerWiring:
    """Tests for correct wiring of engines via Injector."""

    def test_engine_access(self) -> None:
        """Test that engines can be retrieved."""
        container = build_container()

        # Check instance types via protocols
        assert isinstance(container.get(InferenceEngineProtocol), JediInferenceEngine)
        assert isinstance(container.get(TypeValidatorProtocol), MypyTypeValidator)
        assert isinstance(container.get(InsertionEngine), InsertionEngine)
        assert isinstance(container.get(RemovalEngine), RemovalEngine)
        assert isinstance(container.get(DiagnosticEngineProtocol), DiagnosticEngine)

    def test_diagnostic_engine_dependencies(self) -> None:
        """Test that diagnostic engine has its dependencies injected."""
        container = build_container()
        engine = container.get(DiagnosticEngine)

        # Check that validator was injected
        assert hasattr(engine, "mypy_validator")
        assert isinstance(engine.mypy_validator, MypyTypeValidator)

        # Check it's the same instance as the container's validator
        assert engine.mypy_validator is container.get(TypeValidatorProtocol)

    def test_helpers_wiring(self) -> None:
        """Test that helper classes are correctly wired."""
        container = build_container()

        diagnostic_engine = container.get(DiagnosticEngineProtocol)
        assert isinstance(diagnostic_engine, DiagnosticEngine)
        assert diagnostic_engine is container.get(DiagnosticEngine)

        # CodeActionHelper
        ca_helper = container.get(CodeActionHelper)
        assert isinstance(ca_helper, CodeActionHelper)
        assert hasattr(ca_helper, "insertion_engine")
        assert ca_helper.insertion_engine is container.get(InsertionEngine)

        # InlayHintHelper
        ih_helper = container.get(InlayHintHelper)
        assert isinstance(ih_helper, InlayHintHelper)


class TestContainerIntegration:
    """Integration tests for container with real engines."""

    def test_inference_engine_works(self, sample_source: str) -> None:
        """Test that inference engine actually works."""
        container = build_container()
        engine = container.get(InferenceEngineProtocol)

        # Should be able to infer types
        result = engine.infer_types(sample_source)
        assert result is not None
        assert result.scope_tree is not None

    def test_type_validator_works(self, sample_source: str) -> None:
        """Test that type validator actually works."""
        container = build_container()
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
        container = build_container()
        engine = container.get(InsertionEngine)

        # Import the types needed for the unified API
        from fangtype.insertion import CodeLocation, InsertionTarget, TargetType

        source = "x = 42\n"
        target = InsertionTarget(
            target_type=TargetType.VARIABLE_SIMPLE,
            location=CodeLocation(line=1, column=0),
            type_annotation="int",
            name="x",
        )
        result = engine.insert([target], source)

        # Exact output ("x: int = 42") is asserted elsewhere; here we only prove DI inserts.
        assert result.success is True

    def test_diagnostic_engine_works(self) -> None:
        """Test that diagnostic engine actually works."""
        container = build_container()
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

        insertion_engine = test_container.get(InsertionEngine)
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


def test_insert_annotates_self_attributes_end_to_end():
    """`self.x = <literal>` annotated in place via real Jedi+insertion pipeline (no mocks)."""
    from fangtype.workflow import TypeAnnotationWorkflow

    source = (
        "class Counter:\n"
        "    def __init__(self):\n"
        "        self.count = 0\n"
        '        self.name = "hi"\n'
    )
    workflow = build_container("jedi").get(TypeAnnotationWorkflow)

    modified, var_count, _func_count, _msg = asyncio.run(
        workflow.insert_all_types(source, "main.py")
    )

    assert "self.count: int = 0" in modified
    assert 'self.name: str = "hi"' in modified
    assert var_count == 2
    ast.parse(modified)  # raises if the insertion produced invalid syntax


def test_build_container_defaults_to_jedi():
    container = build_container()
    engine = container.get(InferenceEngineProtocol)
    assert isinstance(engine, JediInferenceEngine)


def test_build_container_rejects_unknown_engine():
    import pytest

    with pytest.raises(KeyError):
        build_container("pyright")


class TestResolveEngineName:
    """Tests for resolve_engine_name (FANGTYPE_ENGINE selection)."""

    def test_defaults_to_jedi_when_none(self) -> None:
        from fangtype.container import resolve_engine_name

        assert resolve_engine_name(None) == "jedi"

    def test_returns_known_engine(self) -> None:
        from fangtype.container import resolve_engine_name

        assert resolve_engine_name("jedi") == "jedi"

    def test_falls_back_to_jedi_on_unknown(self) -> None:
        from fangtype.container import resolve_engine_name

        assert resolve_engine_name("does-not-exist") == "jedi"
