"""Tests for type annotation workflow orchestration."""

from unittest.mock import AsyncMock, MagicMock

import pytest

import auto_type.workflow as workflow_module
from auto_type.insertion.target_factory import build_source_index as build_source_index_impl
from auto_type.utils.settings import Settings
from auto_type.validation import MypyDiagnostic
from auto_type.workflow import TypeAnnotationWorkflow


def _validation_result(type_str: str, is_valid: bool) -> MypyDiagnostic:
    """Build a validation result for mocked workflow tests."""
    return MypyDiagnostic(
        line=0,
        column=0,
        end_column=None,
        message="" if is_valid else "Validation failed",
        error_code=None,
        severity="note" if is_valid else "error",
        key=None,
        type_str=type_str,
        is_valid=is_valid,
    )


@pytest.fixture
def mock_settings() -> Settings:
    return Settings()


@pytest.fixture
def mock_inference_engine() -> MagicMock:
    mock = MagicMock()
    mock.infer_types = MagicMock()
    return mock


@pytest.fixture
def mock_insertion_engine() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_type_validator() -> MagicMock:
    mock = MagicMock()
    mock.validate_insertion = AsyncMock()
    mock.validate_bulk = AsyncMock()
    return mock


@pytest.fixture
def workflow(
    mock_inference_engine: MagicMock,
    mock_insertion_engine: MagicMock,
    mock_type_validator: MagicMock,
    mock_settings: Settings,
) -> TypeAnnotationWorkflow:
    return TypeAnnotationWorkflow(
        mock_inference_engine, mock_insertion_engine, mock_type_validator, mock_settings
    )


class TestInsertSingleType:
    """Tests for insert_single_type."""

    async def test_insert_single_type_success(
        self,
        workflow: TypeAnnotationWorkflow,
        mock_type_validator: MagicMock,
        mock_insertion_engine: MagicMock,
    ) -> None:
        """Test successful single type insertion."""
        mock_type_validator.validate_insertion.return_value = (True, "")
        mock_type_validator.validate_bulk.return_value = {
            "_single": _validation_result("int", True)
        }

        # Configure unified API mock
        from auto_type.insertion.types import InsertionResult

        mock_result = InsertionResult(
            success=True,
            modified_source="modified",
            inserted_count=1,
            error_message=None,
            details={},
            failed_targets=[],
        )
        mock_insertion_engine.insert.return_value = mock_result

        source, success, msg = await workflow.insert_single_type("source", "x", "int")

        assert success is True
        assert source == "modified"
        assert "Inserted int" in msg
        # Verify that insert() was called with correct arguments
        mock_insertion_engine.insert.assert_called_once()

    async def test_insert_single_type_validation_fail(
        self, workflow: TypeAnnotationWorkflow, mock_type_validator: MagicMock
    ) -> None:
        """Test when validation fails."""
        mock_type_validator.validate_bulk.return_value = {
            "_single": _validation_result("int", False)
        }

        source, success, msg = await workflow.insert_single_type("source", "x", "int")

        assert success is False
        assert "validation failed" in msg
        assert source == "source"


class TestInsertAllTypes:
    """Tests for insert_all_types."""

    async def test_insert_all_types_success(
        self,
        workflow: TypeAnnotationWorkflow,
        mock_inference_engine: MagicMock,
        mock_type_validator: MagicMock,
        mock_insertion_engine: MagicMock,
    ) -> None:
        """Test successful bulk insertion."""
        mock_inference_result = MagicMock()
        mock_inference_result.get_variable_insertions.return_value = {"x": "int"}
        mock_inference_result.get_function_insertions.return_value = {}
        mock_inference_result.get_all_insertable_types.return_value = {"functions": {}}
        mock_inference_engine.infer_types.return_value = mock_inference_result

        mock_type_validator.validate_bulk.return_value = {"x": _validation_result("int", True)}

        # Configure unified API mock
        from auto_type.insertion.types import InsertionResult

        mock_result = InsertionResult(
            success=True,
            modified_source="modified",
            inserted_count=1,
            error_message=None,
            details={},
            failed_targets=[],
        )
        mock_insertion_engine.insert.return_value = mock_result

        source, var_count, _func_count, msg = await workflow.insert_all_types("source", "file.py")

        assert var_count == 1
        assert source == "modified"
        assert "Inserted 1 type annotations" in msg

    async def test_insert_all_types_no_types_found(
        self,
        workflow: TypeAnnotationWorkflow,
        mock_inference_engine: MagicMock,
        mock_type_validator: MagicMock,
        mock_insertion_engine: MagicMock,
    ) -> None:
        """Test when no types are inferred."""
        mock_inference_result = MagicMock()
        mock_inference_result.get_variable_insertions.return_value = {}
        mock_inference_result.get_function_insertions.return_value = {}
        mock_inference_result.get_attribute_insertions.return_value = {}
        mock_inference_engine.infer_types.return_value = mock_inference_result

        _source, vars_cnt, funcs_cnt, msg = await workflow.insert_all_types("source", "file.py")

        assert vars_cnt == 0
        assert funcs_cnt == 0
        assert "No types to insert" in msg
        mock_insertion_engine.insert_types_bulk.assert_not_called()

    async def test_insert_all_types_validation_fail(
        self,
        workflow: TypeAnnotationWorkflow,
        mock_inference_engine: MagicMock,
        mock_type_validator: MagicMock,
        mock_insertion_engine: MagicMock,
    ) -> None:
        """Test when all types fail validation."""
        mock_inference_result = MagicMock()
        mock_inference_result.get_variable_insertions.return_value = {"x": "int"}
        mock_inference_result.get_function_insertions.return_value = {}
        mock_inference_engine.infer_types.return_value = mock_inference_result

        mock_type_validator.validate_bulk.return_value = {}

        _source, vars_cnt, _funcs_cnt, msg = await workflow.insert_all_types("source", "file.py")

        assert vars_cnt == 0
        assert "No types inserted" in msg or "No valid types" in msg
        mock_insertion_engine.insert.assert_not_called()

    async def test_insert_all_types_builds_source_index_once(
        self,
        workflow: TypeAnnotationWorkflow,
        mock_inference_engine: MagicMock,
        mock_type_validator: MagicMock,
        mock_insertion_engine: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Bulk insertion should parse/index source once per request."""
        source = "x = 1\ny = 2\n"
        mock_inference_result = MagicMock()
        mock_inference_result.get_variable_insertions.return_value = {
            (0, "x"): "int",
            (1, "y"): "int",
        }
        mock_inference_result.get_function_insertions.return_value = {}
        mock_inference_result.get_attribute_insertions.return_value = {}
        mock_inference_engine.infer_types.return_value = mock_inference_result

        mock_type_validator.validate_bulk.return_value = {
            (0, "x"): _validation_result("int", True),
            (1, "y"): _validation_result("int", True),
        }

        from auto_type.insertion.types import InsertionResult

        mock_insertion_engine.insert.return_value = InsertionResult(
            success=True,
            modified_source=source,
            inserted_count=2,
            error_message=None,
            details={},
            failed_targets=[],
        )

        calls = {"count": 0}

        def counting_build_source_index(content: str) -> object | None:
            calls["count"] += 1
            return build_source_index_impl(content)

        monkeypatch.setattr(workflow_module, "build_source_index", counting_build_source_index)

        await workflow.insert_all_types(source, "file.py")

        assert calls["count"] == 1


class TestPreviewInsertions:
    """Tests for preview_insertions."""

    async def test_preview_insertions_success(
        self,
        workflow: TypeAnnotationWorkflow,
        mock_inference_engine: MagicMock,
        mock_type_validator: MagicMock,
        mock_insertion_engine: MagicMock,
    ) -> None:
        """Test successful preview."""
        mock_inference_result = MagicMock()
        mock_inference_result.get_variable_insertions.return_value = {"x": "int"}
        mock_inference_result.get_function_insertions.return_value = {}
        mock_inference_engine.infer_types.return_value = mock_inference_result

        mock_type_validator.validate_bulk.return_value = {"x": _validation_result("int", True)}

        expected_preview = {
            "success": True,
            "will_insert": [{"variable": "x", "type": "int"}],
            "total_changes": 1,
        }
        mock_insertion_engine.preview_insertions.return_value = expected_preview

        preview = await workflow.preview_insertions("source")
        assert preview == expected_preview

    async def test_preview_insertions_no_types(
        self, workflow: TypeAnnotationWorkflow, mock_inference_engine: MagicMock
    ) -> None:
        """Test preview when no types inferred."""
        mock_inference_result = MagicMock()
        mock_inference_result.get_variable_insertions.return_value = {}
        mock_inference_result.get_function_insertions.return_value = {}
        mock_inference_result.get_attribute_insertions.return_value = {}
        mock_inference_engine.infer_types.return_value = mock_inference_result

        preview = await workflow.preview_insertions("source")
        assert preview["success"] is True
        assert preview["total_changes"] == 0


class TestTypeCollection:
    """Tests for shared type collection paths."""

    async def test_collect_and_validate_types_uses_shared_pipeline(
        self,
        workflow: TypeAnnotationWorkflow,
        mock_type_validator: MagicMock,
    ) -> None:
        """Validated collection should call validator with shared collection output."""
        mock_inference_result = MagicMock()
        all_types = {"module.var.x": "int"}
        validated = {"module.var.x": _validation_result("int", True)}

        workflow._inference_engine.infer_types = MagicMock(return_value=mock_inference_result)
        workflow._collect_types_from_scopes = MagicMock(  # type: ignore[method-assign]
            return_value=all_types
        )
        workflow._settings.mypy_inference_validation_enabled = True
        mock_type_validator.validate_bulk.return_value = validated

        inference_result, validation_results = await workflow.collect_and_validate_types(
            "source", "file.py"
        )

        assert inference_result is mock_inference_result
        assert validation_results == validated
        workflow._inference_engine.infer_types.assert_called_once_with(
            "source",
            path="file.py",
        )
        workflow._collect_types_from_scopes.assert_called_once_with(mock_inference_result)
        mock_type_validator.validate_bulk.assert_awaited_once_with(all_types, "source")

    async def test_collect_and_validate_types_skips_mypy_when_inference_validation_disabled(
        self,
        workflow: TypeAnnotationWorkflow,
        mock_type_validator: MagicMock,
    ) -> None:
        """Collection should return optimistic results when inference validation is disabled."""
        mock_inference_result = MagicMock()
        all_types = {"module.var.x": "int", "func_foo.param.y": "str"}

        workflow._settings.mypy_inference_validation_enabled = False
        workflow._inference_engine.infer_types = MagicMock(return_value=mock_inference_result)
        workflow._collect_types_from_scopes = MagicMock(  # type: ignore[method-assign]
            return_value=all_types
        )

        inference_result, validation_results = await workflow.collect_and_validate_types(
            "source", "file.py"
        )

        assert inference_result is mock_inference_result
        assert set(validation_results.keys()) == set(all_types.keys())
        assert all(result.is_valid for result in validation_results.values())
        assert validation_results["module.var.x"].type_str == "int"
        assert validation_results["func_foo.param.y"].type_str == "str"
        mock_type_validator.validate_bulk.assert_not_awaited()
