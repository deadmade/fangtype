"""Tests for TypeEvalPy benchmark integration."""

import ast

from auto_type.inference.literal_inference import LiteralInferenceEngine
from tests.benchmarks.typeevalpy.analyzer import (
    estimate_implementation_effort,
    extract_code_examples,
)
from tests.benchmarks.typeevalpy.loader import (
    AnnotationType,
    BenchmarkCase,
    categorize_annotation,
)
from tests.benchmarks.typeevalpy.runner import (
    InferenceResult,
    ResultStatus,
    classify_unsupported_pattern,
    run_inference_on_case,
    type_matches,
)


class TestAnnotationCategorization:
    def test_simple_variable(self):
        ann = {"variable": "x", "type": ["int"]}
        assert categorize_annotation(ann) == AnnotationType.SIMPLE_VARIABLE

    def test_complex_variable_subscript(self):
        ann = {"variable": "items[0]", "type": ["int"]}
        assert categorize_annotation(ann) == AnnotationType.COMPLEX_VARIABLE

    def test_complex_variable_attribute(self):
        ann = {"variable": "obj.attr", "type": ["str"]}
        assert categorize_annotation(ann) == AnnotationType.COMPLEX_VARIABLE

    def test_function_return(self):
        ann = {"function": "func", "type": ["int"]}
        assert categorize_annotation(ann) == AnnotationType.FUNCTION_RETURN

    def test_function_param(self):
        ann = {"function": "func", "parameter": "a", "type": ["int"]}
        assert categorize_annotation(ann) == AnnotationType.FUNCTION_PARAM

    def test_other(self):
        ann = {"something_else": "value", "type": ["int"]}
        assert categorize_annotation(ann) == AnnotationType.OTHER


class TestTypeMatching:
    def test_exact_match(self):
        assert type_matches("int", ["int"]) is True
        assert type_matches("str", ["str"]) is True
        assert type_matches("bool", ["bool"]) is True

    def test_generic_match(self):
        assert type_matches("list", ["list[int]"]) is True
        assert type_matches("dict", ["dict[str, int]"]) is True
        assert type_matches("set", ["set[str]"]) is True

    def test_mismatch(self):
        assert type_matches("int", ["str"]) is False
        assert type_matches("list", ["dict"]) is False

    def test_multiple_expected(self):
        assert type_matches("int", ["str", "int", "bool"]) is True
        assert type_matches("list", ["dict", "list[str]"]) is True


class TestPatternClassification:
    def test_function_call(self):
        code = "x = func()"
        tree = ast.parse(code)
        assign = tree.body[0]
        pattern = classify_unsupported_pattern(assign.value)
        assert pattern == "function_call"

    def test_binary_operation(self):
        code = "x = 1 + 2"
        tree = ast.parse(code)
        assign = tree.body[0]
        pattern = classify_unsupported_pattern(assign.value)
        assert pattern == "binary_operation"

    def test_unary_operation(self):
        code = "x = -42"
        tree = ast.parse(code)
        assign = tree.body[0]
        pattern = classify_unsupported_pattern(assign.value)
        assert pattern == "unary_operation"

    def test_subscript(self):
        code = "x = items[0]"
        tree = ast.parse(code)
        assign = tree.body[0]
        pattern = classify_unsupported_pattern(assign.value)
        assert pattern == "subscript"


class TestInferenceIntegration:
    def test_correct_inference(self, tmp_path):
        """Test correct inference on simple case."""
        py_file = tmp_path / "main.py"
        py_file.write_text("x = 42")

        case = BenchmarkCase(
            file_path=py_file,
            source_code="x = 42",
            line_number=1,
            col_offset=0,
            variable_name="x",
            function_name=None,
            parameter_name=None,
            expected_types=["int"],
            category="test",
            annotation_type=AnnotationType.SIMPLE_VARIABLE,
        )

        engine = LiteralInferenceEngine()
        result = run_inference_on_case(case, engine)

        assert result.status == ResultStatus.CORRECT
        assert result.inferred_type == "int"

    def test_incorrect_inference(self, tmp_path):
        """Test when inference produces wrong type."""
        py_file = tmp_path / "main.py"
        py_file.write_text("x = 42")

        case = BenchmarkCase(
            file_path=py_file,
            source_code="x = 42",
            line_number=1,
            col_offset=0,
            variable_name="x",
            function_name=None,
            parameter_name=None,
            expected_types=["str"],  # Wrong expectation for testing
            category="test",
            annotation_type=AnnotationType.SIMPLE_VARIABLE,
        )

        engine = LiteralInferenceEngine()
        result = run_inference_on_case(case, engine)

        assert result.status == ResultStatus.INCORRECT
        assert result.inferred_type == "int"

    def test_unsupported_pattern(self, tmp_path):
        """Test unsupported pattern detection."""
        py_file = tmp_path / "main.py"
        py_file.write_text("x = func()")

        case = BenchmarkCase(
            file_path=py_file,
            source_code="x = func()",
            line_number=1,
            col_offset=0,
            variable_name="x",
            function_name=None,
            parameter_name=None,
            expected_types=["int"],
            category="test",
            annotation_type=AnnotationType.SIMPLE_VARIABLE,
        )

        engine = LiteralInferenceEngine()
        result = run_inference_on_case(case, engine)

        assert result.status == ResultStatus.UNSUPPORTED
        assert result.reason == "function_call"

    def test_out_of_scope(self, tmp_path):
        """Test out-of-scope annotation (function return)."""
        py_file = tmp_path / "main.py"
        py_file.write_text("def func():\n    return 42")

        case = BenchmarkCase(
            file_path=py_file,
            source_code="def func():\n    return 42",
            line_number=1,
            col_offset=0,
            variable_name=None,
            function_name="func",
            parameter_name=None,
            expected_types=["int"],
            category="test",
            annotation_type=AnnotationType.FUNCTION_RETURN,
        )

        engine = LiteralInferenceEngine()
        result = run_inference_on_case(case, engine)

        assert result.status == ResultStatus.OUT_OF_SCOPE


class TestEffortEstimation:
    def test_quick_wins(self):
        assert estimate_implementation_effort("unary_operation") == "quick_win"
        assert estimate_implementation_effort("binary_operation") == "quick_win"

    def test_medium_effort(self):
        assert estimate_implementation_effort("function_call") == "medium"
        assert estimate_implementation_effort("subscript") == "medium"
        assert estimate_implementation_effort("attribute_access") == "medium"

    def test_long_term(self):
        assert estimate_implementation_effort("unknown_pattern") == "long_term"
        assert estimate_implementation_effort("lambda") == "long_term"


class TestCodeExampleExtraction:
    def test_extract_examples(self, tmp_path):
        """Test extracting code examples from results."""
        py_file = tmp_path / "main.py"
        py_file.write_text("x = 1 + 2\ny = func()\nz = items[0]")

        cases = [
            InferenceResult(
                case=BenchmarkCase(
                    file_path=py_file,
                    source_code="x = 1 + 2\ny = func()\nz = items[0]",
                    line_number=1,
                    col_offset=0,
                    variable_name="x",
                    function_name=None,
                    parameter_name=None,
                    expected_types=["int"],
                    category="test",
                    annotation_type=AnnotationType.SIMPLE_VARIABLE,
                ),
                status=ResultStatus.UNSUPPORTED,
                inferred_type=None,
                reason="binary_operation",
            )
        ]

        examples = extract_code_examples(cases, max_examples=3)
        assert len(examples) == 1
        assert "x" in examples[0]
        assert "1 + 2" in examples[0]
