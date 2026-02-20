"""Unit tests for insertion benchmark modules."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from auto_type.insertion import TargetType
from auto_type.protocols import TypeAnnotationWorkflowProtocol
from benchmark.insertion.loader import load_insertable_cases
from benchmark.insertion.runner import (
    InsertionStatus,
    _create_variable_target_for_case,
    _resolve_function_target,
    run_insertion_on_case,
)
from benchmark.insertion.validator import (
    validate_insertion_result,
    validate_syntax,
    validate_type_match,
    verify_annotation_inserted,
    verify_function_annotation_inserted,
)
from benchmark.typeevalpy.loader import AnnotationType, BenchmarkCase


class TestLoader:
    """Test insertion benchmark loader functions."""

    def test_load_insertable_cases_returns_all_cases(self) -> None:
        """Test that load_insertable_cases returns all benchmark cases."""
        try:
            cases = load_insertable_cases()
            assert len(cases) > 0
            types_present = {case.annotation_type for case in cases}
            assert len(types_present) > 1
        except FileNotFoundError:
            pass


class TestValidator:
    """Test insertion benchmark validator functions."""

    def test_validate_syntax_valid_code(self) -> None:
        source = "x: int = 42\n"
        is_valid, error = validate_syntax(source)
        assert is_valid
        assert error is None

    def test_validate_syntax_invalid_code(self) -> None:
        source = "x: int = @#$% invalid"
        is_valid, error = validate_syntax(source)
        assert not is_valid
        assert error is not None

    def test_validate_type_match_exact(self) -> None:
        assert validate_type_match("int", ["int"])

    def test_verify_annotation_inserted_success(self) -> None:
        original = "x = 42\n"
        modified = "x: int = 42\n"
        was_inserted, error = verify_annotation_inserted(original, modified, "x", 1)
        assert was_inserted
        assert error is None

    def test_verify_function_annotation_inserted_kwargs_success(self) -> None:
        modified = "def concatenate(**kwargs: dict[str, object]):\n    return kwargs\n"
        inserted, error = verify_function_annotation_inserted(
            modified,
            "concatenate",
            "param",
            "kwargs",
        )
        assert inserted
        assert error is None

    def test_validate_insertion_result_success(self) -> None:
        case = BenchmarkCase(
            file_path=Path("/tmp/test.py"),
            source_code="x = 42\n",
            line_number=1,
            col_offset=0,
            variable_name="x",
            function_name=None,
            parameter_name=None,
            expected_types=["int"],
            category="test",
            annotation_type=AnnotationType.SIMPLE_VARIABLE,
        )
        original = "x = 42\n"
        modified = "x: int = 42\n"
        inferred = "int"

        result = validate_insertion_result(case, original, modified, inferred, True)

        assert result["syntax_valid"]
        assert result["annotation_inserted"]
        assert result["type_matches"]


class TestRunner:
    """Test insertion benchmark runner."""

    def test_run_insertion_on_case_success(self) -> None:
        case = BenchmarkCase(
            file_path=Path("/tmp/test.py"),
            source_code="x = 42\n",
            line_number=1,
            col_offset=0,
            variable_name="x",
            function_name=None,
            parameter_name=None,
            expected_types=["int"],
            category="test",
            annotation_type=AnnotationType.SIMPLE_VARIABLE,
        )

        result = asyncio.run(run_insertion_on_case(case))
        assert result.status == InsertionStatus.CORRECT

    def test_run_insertion_on_case_inference_failure(self, monkeypatch) -> None:
        import benchmark.insertion.runner as runner_module

        case = BenchmarkCase(
            file_path=Path("/tmp/test.py"),
            source_code="x = unknown()\n",
            line_number=1,
            col_offset=0,
            variable_name="x",
            function_name=None,
            parameter_name=None,
            expected_types=["int"],
            category="test",
            annotation_type=AnnotationType.SIMPLE_VARIABLE,
        )

        mock_workflow = MagicMock()
        mock_workflow.annotate_target_with_fallbacks = AsyncMock(
            return_value={
                "inferred_type": None,
                "modified_source": case.source_code,
                "insertion_success": False,
                "error_message": "Could not infer type",
            }
        )

        class FakeContainer:
            def get(self, key):
                if key is TypeAnnotationWorkflowProtocol:
                    return mock_workflow
                return MagicMock()

        monkeypatch.setattr(runner_module, "get_container", lambda: FakeContainer())

        result = asyncio.run(run_insertion_on_case(case))
        assert result.status == InsertionStatus.INFERENCE_FAILED

    def test_create_variable_target_detects_complex_assignment(self) -> None:
        source = "a, b = 1, 2\n"
        target = _create_variable_target_for_case(source, "a", "int", 1)
        assert target.target_type == TargetType.VARIABLE_COMPLEX

    def test_resolve_function_target_qualified_name(self) -> None:
        source = """
class Cls:
    def __next__(self):
        return 1
"""
        line, simple_name = _resolve_function_target(source, "Cls.__next__")
        assert simple_name == "__next__"
        assert line == 3

    def test_run_insertion_on_case_delegates_to_workflow(self, monkeypatch) -> None:
        import benchmark.insertion.runner as runner_module

        case = BenchmarkCase(
            file_path=Path("/tmp/test.py"),
            source_code="x = 42\n",
            line_number=1,
            col_offset=0,
            variable_name="x",
            function_name=None,
            parameter_name=None,
            expected_types=["int"],
            category="test",
            annotation_type=AnnotationType.SIMPLE_VARIABLE,
        )

        mock_workflow = MagicMock()
        mock_workflow.annotate_target_with_fallbacks = AsyncMock(
            return_value={
                "inferred_type": "int",
                "modified_source": "x: int = 42\n",
                "insertion_success": True,
                "error_message": None,
            }
        )

        class FakeContainer:
            def get(self, key):
                if key is TypeAnnotationWorkflowProtocol:
                    return mock_workflow
                return MagicMock()

        monkeypatch.setattr(runner_module, "get_container", lambda: FakeContainer())

        result = asyncio.run(run_insertion_on_case(case))
        assert result.status == InsertionStatus.CORRECT
        mock_workflow.annotate_target_with_fallbacks.assert_called_once()
