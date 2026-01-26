"""Tests for type annotation workflow orchestration."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from auto_type.workflow import TypeAnnotationWorkflow


@pytest.fixture
def mock_inference_engine():
    mock = MagicMock()
    mock.infer_types = AsyncMock()
    mock.infer_variable_types = AsyncMock()
    return mock


@pytest.fixture
def mock_insertion_engine():
    return MagicMock()


@pytest.fixture
def mock_type_validator():
    mock = MagicMock()
    mock.validate_insertion = AsyncMock()
    mock.validate_bulk = AsyncMock()
    mock.validate = AsyncMock()
    return mock


@pytest.fixture
def workflow(mock_inference_engine, mock_insertion_engine, mock_type_validator):
    return TypeAnnotationWorkflow(mock_inference_engine, mock_insertion_engine, mock_type_validator)


class TestInsertSingleType:
    """Tests for insert_single_type."""

    async def test_insert_single_type_success(
        self, workflow, mock_type_validator, mock_insertion_engine
    ) -> None:
        """Test successful single type insertion."""
        mock_type_validator.validate_insertion.return_value = (True, "")

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

    async def test_insert_single_type_validation_fail(self, workflow, mock_type_validator) -> None:
        """Test when validation fails."""
        mock_type_validator.validate_insertion.return_value = (False, "error")

        source, success, msg = await workflow.insert_single_type("source", "x", "int")

        assert success is False
        assert "validation failed" in msg
        assert source == "source"


class TestInsertAllTypes:
    """Tests for insert_all_types."""

    async def test_insert_all_types_success(
        self, workflow, mock_inference_engine, mock_type_validator, mock_insertion_engine
    ) -> None:
        """Test successful bulk insertion."""
        mock_inference_result = MagicMock()
        mock_inference_result.get_variable_insertions.return_value = {"x": "int"}
        mock_inference_result.get_function_insertions.return_value = {}
        mock_inference_result.get_all_insertable_types.return_value = {"functions": {}}
        mock_inference_engine.infer_types.return_value = mock_inference_result

        mock_type_validator.validate_bulk.return_value = {"x": "int"}

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

        source, var_count, func_count, msg = await workflow.insert_all_types("source", "file.py")

        assert var_count == 1
        assert source == "modified"
        assert "Inserted 1 type annotations" in msg

    async def test_insert_all_types_no_types_found(
        self, workflow, mock_inference_engine, mock_insertion_engine
    ) -> None:
        """Test when no types are inferred."""
        mock_inference_result = MagicMock()
        mock_inference_result.get_variable_insertions.return_value = {}
        mock_inference_result.get_function_insertions.return_value = {}
        mock_inference_engine.infer_types.return_value = mock_inference_result

        source, vars_cnt, funcs_cnt, msg = await workflow.insert_all_types("source", "file.py")

        assert vars_cnt == 0
        assert funcs_cnt == 0
        assert "No types to insert" in msg
        mock_insertion_engine.insert_types_bulk.assert_not_called()

    async def test_insert_all_types_validation_fail(
        self, workflow, mock_inference_engine, mock_type_validator, mock_insertion_engine
    ) -> None:
        """Test when all types fail validation."""
        mock_inference_result = MagicMock()
        mock_inference_result.get_variable_insertions.return_value = {"x": "int"}
        mock_inference_result.get_function_insertions.return_value = {}
        mock_inference_engine.infer_types.return_value = mock_inference_result

        mock_type_validator.validate_bulk.return_value = {}

        source, vars_cnt, funcs_cnt, msg = await workflow.insert_all_types("source", "file.py")

        assert vars_cnt == 0
        assert "No valid types" in msg
        mock_insertion_engine.insert_types_bulk.assert_not_called()


class TestPreviewInsertions:
    """Tests for preview_insertions."""

    async def test_preview_insertions_success(
        self, workflow, mock_inference_engine, mock_type_validator, mock_insertion_engine
    ) -> None:
        """Test successful preview."""
        mock_inference_result = MagicMock()
        mock_inference_result.get_variable_insertions.return_value = {"x": "int"}
        mock_inference_engine.infer_types.return_value = mock_inference_result

        mock_type_validator.validate_bulk.return_value = {"x": "int"}

        expected_preview = {
            "success": True,
            "will_insert": [{"variable": "x", "type": "int"}],
            "total_changes": 1,
        }
        mock_insertion_engine.preview_insertions.return_value = expected_preview

        preview = await workflow.preview_insertions("source")
        assert preview == expected_preview

    async def test_preview_insertions_no_types(self, workflow, mock_inference_engine) -> None:
        """Test preview when no types inferred."""
        mock_inference_result = MagicMock()
        mock_inference_result.get_variable_insertions.return_value = {}
        mock_inference_engine.infer_types.return_value = mock_inference_result

        preview = await workflow.preview_insertions("source")
        assert preview["success"] is True
        assert preview["total_changes"] == 0
