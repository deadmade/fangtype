"""Unit tests for insertion benchmark modules."""

import asyncio
from pathlib import Path

from tests.benchmarks.insertion.loader import load_insertable_cases
from tests.benchmarks.insertion.runner import InsertionStatus, run_insertion_on_case
from tests.benchmarks.insertion.validator import (
    validate_insertion_result,
    validate_syntax,
    validate_type_match,
    verify_annotation_inserted,
)
from tests.benchmarks.typeevalpy.loader import AnnotationType, BenchmarkCase


class TestLoader:
    """Test insertion benchmark loader functions.

    Note: Filtering has been removed - load_insertable_cases now returns
    ALL benchmark cases. These tests verify the loader works correctly.
    """

    def test_load_insertable_cases_returns_all_cases(self) -> None:
        """Test that load_insertable_cases returns all benchmark cases."""
        # This test requires the TypeEvalPy benchmark to be present
        # We'll just verify the function can be called without errors
        try:
            cases = load_insertable_cases()
            # Should load ~845 total cases (no filtering)
            assert len(cases) > 0
            # Should include various annotation types (not just simple variables)
            types_present = {case.annotation_type for case in cases}
            assert len(types_present) > 1  # More than just SIMPLE_VARIABLE
        except FileNotFoundError:
            # Benchmark not present - skip test
            pass


class TestValidator:
    """Test insertion benchmark validator functions."""

    def test_validate_syntax_valid_code(self) -> None:
        """Test syntax validation of valid code."""
        source = "x: int = 42\n"
        is_valid, error = validate_syntax(source)
        assert is_valid
        assert error is None

    def test_validate_syntax_invalid_code(self) -> None:
        """Test syntax validation of invalid code."""
        source = "x: int = @#$% invalid"
        is_valid, error = validate_syntax(source)
        assert not is_valid
        assert error is not None
        assert "Syntax" in error or "syntax" in error or "error" in error.lower()

    def test_validate_type_match_exact(self) -> None:
        """Test exact type match."""
        assert validate_type_match("int", ["int"])
        assert validate_type_match("str", ["str", "int"])

    def test_validate_type_match_generic(self) -> None:
        """Test generic type match."""
        assert validate_type_match("list", ["list[int]"])
        assert validate_type_match("dict", ["dict[str, int]"])

    def test_validate_type_match_no_match(self) -> None:
        """Test type mismatch."""
        assert not validate_type_match("int", ["str"])
        assert not validate_type_match("list", ["dict"])

    def test_verify_annotation_inserted_success(self) -> None:
        """Test successful annotation insertion verification."""
        original = "x = 42\n"
        modified = "x: int = 42\n"
        was_inserted, error = verify_annotation_inserted(original, modified, "x", 1)
        assert was_inserted
        assert error is None

    def test_verify_annotation_inserted_failure(self) -> None:
        """Test annotation insertion verification failure."""
        original = "x = 42\n"
        modified = "x = 42\n"  # No change
        was_inserted, error = verify_annotation_inserted(original, modified, "x", 1)
        assert not was_inserted
        assert error is not None

    def test_validate_insertion_result_success(self) -> None:
        """Test comprehensive validation of successful insertion."""
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

    def test_validate_insertion_result_type_mismatch(self) -> None:
        """Test validation with type mismatch."""
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
        modified = "x: str = 42\n"
        inferred = "str"

        result = validate_insertion_result(case, original, modified, inferred, True)

        assert result["syntax_valid"]
        assert result["annotation_inserted"]
        assert not result["type_matches"]


class TestRunner:
    """Test insertion benchmark runner."""

    def test_run_insertion_on_case_success(self) -> None:
        """Test successful insertion on a simple case.

        Uses the DI container internally via run_insertion_on_case.
        """
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

        # Should infer int and insert successfully
        assert result.inferred_type == "int"
        assert result.insertion_success
        assert result.syntax_valid
        assert result.type_matches
        assert result.status == InsertionStatus.CORRECT

    def test_run_insertion_on_case_inference_failure(self) -> None:
        """Test insertion on case where inference fails.

        Uses the DI container internally via run_insertion_on_case.
        """
        case = BenchmarkCase(
            file_path=Path("/tmp/test.py"),
            source_code="x = some_unknown_function()\n",
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

        # Should fail at inference stage
        assert result.status == InsertionStatus.INFERENCE_FAILED
        assert result.inferred_type is None
        assert not result.insertion_success
