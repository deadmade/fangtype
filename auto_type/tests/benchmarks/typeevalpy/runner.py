"""Run inference on benchmark cases and categorize results."""

import ast
from dataclasses import dataclass
from enum import Enum

from auto_type.inference import UnifiedInferenceEngine
from tests.benchmarks.typeevalpy.loader import AnnotationType, BenchmarkCase


class ResultStatus(Enum):
    """Status of inference result."""

    CORRECT = "correct"  # ✅ Inferred correctly
    INCORRECT = "incorrect"  # ❌ Inferred wrong type
    UNSUPPORTED = "unsupported"  # ⚠️ Couldn't infer (returns None)
    OUT_OF_SCOPE = "out_of_scope"  # 🔵 Not a simple variable


@dataclass
class InferenceResult:
    """Result of running inference on one annotation."""

    case: BenchmarkCase
    status: ResultStatus
    inferred_type: str | None  # What we inferred (if any)
    reason: str | None  # Failure/skip reason


@dataclass
class BenchmarkResults:
    """Complete benchmark results."""

    total: int
    results: list[InferenceResult]

    @property
    def correct(self) -> list[InferenceResult]:
        """Get all correct inferences."""
        return [r for r in self.results if r.status == ResultStatus.CORRECT]

    @property
    def incorrect(self) -> list[InferenceResult]:
        """Get all incorrect inferences."""
        return [r for r in self.results if r.status == ResultStatus.INCORRECT]

    @property
    def unsupported(self) -> list[InferenceResult]:
        """Get all unsupported cases."""
        return [r for r in self.results if r.status == ResultStatus.UNSUPPORTED]

    @property
    def out_of_scope(self) -> list[InferenceResult]:
        """Get all out-of-scope cases."""
        return [r for r in self.results if r.status == ResultStatus.OUT_OF_SCOPE]


def type_matches(inferred: str, expected: list[str]) -> bool:
    """Check if inferred type matches any expected type.

    Handles:
    - Exact matches: "int" == "int"
    - Generic matches: "list" == "list[int]"
    """
    # Exact match
    if inferred in expected:
        return True

    # Partial match: list matches list[int], dict matches dict[str, int]
    return any(exp.startswith(inferred + "[") for exp in expected)


def classify_unsupported_pattern(node: ast.expr) -> str:
    """Classify unsupported pattern (simple, based on AST node type)."""
    match node:
        case ast.Call():
            return "function_call"
        case ast.BinOp():
            return "binary_operation"
        case ast.UnaryOp():
            return "unary_operation"
        case ast.Subscript():
            return "subscript"
        case ast.Attribute():
            return "attribute_access"
        case ast.IfExp():
            return "conditional_expression"
        case ast.Compare():
            return "comparison"
        case ast.BoolOp():
            return "boolean_operation"
        case ast.Lambda():
            return "lambda"
        case ast.GeneratorExp():
            return "generator_expression"
        case _:
            return f"unknown_pattern_{type(node).__name__}"


def analyze_failure(case: BenchmarkCase) -> str:
    """Determine why inference failed by analyzing AST."""
    try:
        tree = ast.parse(case.source_code)

        # Find the assignment at the given line
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and node.lineno == case.line_number:
                # Found the assignment - classify what it is
                return classify_unsupported_pattern(node.value)

        return "assignment_not_found"
    except SyntaxError:
        return "syntax_error"
    except Exception:
        return "analysis_failed"


def run_inference_on_case(case: BenchmarkCase, engine: UnifiedInferenceEngine) -> InferenceResult:
    """Run inference on single case and categorize result."""

    # Skip non-simple-variables (out of scope)
    if case.annotation_type != AnnotationType.SIMPLE_VARIABLE:
        return InferenceResult(
            case=case,
            status=ResultStatus.OUT_OF_SCOPE,
            inferred_type=None,
            reason=f"{case.annotation_type.value}",
        )

    # Run inference to get full scope tree with flow-sensitive types
    result = engine.infer_types(case.source_code)

    # Query type at specific line number (flow-sensitive lookup)
    # Convert 1-based line number (from JSON) to 0-based (internal)
    type_info = result.scope_tree.root.get_variable_type_at_line(
        case.variable_name, case.line_number - 1
    )

    # Check if our variable was inferred
    if type_info is None or type_info.type_str == "Unknown":
        # Analyze WHY it wasn't inferred
        reason = analyze_failure(case)
        return InferenceResult(
            case=case, status=ResultStatus.UNSUPPORTED, inferred_type=None, reason=reason
        )

    # We inferred something - is it correct?
    inferred_type = type_info.type_str

    if type_matches(inferred_type, case.expected_types):
        return InferenceResult(
            case=case, status=ResultStatus.CORRECT, inferred_type=inferred_type, reason=None
        )
    else:
        return InferenceResult(
            case=case,
            status=ResultStatus.INCORRECT,
            inferred_type=inferred_type,
            reason=f"Expected {case.expected_types}",
        )


def run_benchmark(
    cases: list[BenchmarkCase],
    engine: UnifiedInferenceEngine,
    show_progress: bool = True,
) -> BenchmarkResults:
    """Run inference on all cases with progress indicator."""
    results = []
    total = len(cases)

    for i, case in enumerate(cases, 1):
        if show_progress and i % 50 == 0:
            print(f"Progress: [{i}/{total}] ({i / total * 100:.1f}%)")

        result = run_inference_on_case(case, engine)
        results.append(result)

    if show_progress:
        print(f"Progress: [{total}/{total}] (100.0%)")

    return BenchmarkResults(total=total, results=results)
