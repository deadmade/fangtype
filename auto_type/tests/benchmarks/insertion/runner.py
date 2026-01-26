"""Run insertion benchmark: Infer types → Insert annotations → Validate results.

This module orchestrates the complete insertion benchmark workflow.
"""

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Any

from auto_type.container import get_container
from auto_type.inference.inference_result import InferenceResult
from auto_type.insertion import (
    CodeLocation,
    InsertionTarget,
    TargetType,
    UnifiedInsertionEngine,
)
from auto_type.protocols import (
    InferenceEngineProtocol,
    TypeAnnotationWorkflowProtocol,
)
from tests.benchmarks.insertion.validator import (
    validate_insertion_result,
    verify_function_annotation_inserted,
)
from tests.benchmarks.typeevalpy.loader import AnnotationType, BenchmarkCase


class InsertionStatus(Enum):
    """Status of insertion benchmark result."""

    CORRECT = "correct"  # ✅ Inserted correctly, type matches, syntax valid
    TYPE_MISMATCH = "type_mismatch"  # ❌ Inserted but wrong type from inference
    INSERTION_FAILED = "insertion_failed"  # 💥 InsertionEngine failed to insert
    INFERENCE_FAILED = "inference_failed"  # ⚠️ JediInferenceEngine couldn't infer
    SYNTAX_ERROR = "syntax_error"  # 🔍 Inserted code has syntax errors
    ANNOTATION_MISSING = "annotation_missing"  # 📝 Annotation not found in result
    NOT_APPLICABLE = "not_applicable"  # 🔵 Unsupported annotation type


@dataclass
class InsertionResult:
    """Result of running insertion on one benchmark case."""

    case: BenchmarkCase
    status: InsertionStatus
    inferred_type: str | None  # What Jedi inferred
    inserted_source: str | None  # Modified source code
    insertion_success: bool  # Did UnifiedInsertionEngine succeed?
    syntax_valid: bool  # Is result syntactically valid?
    type_matches: bool  # Does type match ground truth?
    reason: str | None  # Failure reason or details


def _find_variable_line(source: str, variable_name: str) -> int:
    """Find the line number where a variable is assigned."""
    lines = source.split("\n")
    for i, line in enumerate(lines, 1):
        if f"{variable_name} =" in line and not line.strip().startswith("#"):
            return i
    return 1  # Fallback to line 1


def _find_function_line(source: str, function_name: str) -> int:
    """Find the line number where a function is defined."""
    lines = source.split("\n")
    for i, line in enumerate(lines, 1):
        if f"def {function_name}(" in line:
            return i
    return 1  # Fallback to line 1


def _create_variable_target(name: str, type_annotation: str, line: int) -> InsertionTarget:
    """Create an InsertionTarget for a variable annotation."""
    return InsertionTarget(
        target_type=TargetType.VARIABLE_SIMPLE,
        location=CodeLocation(line=line, column=0),
        type_annotation=type_annotation,
        name=name,
    )


@dataclass
class InsertionBenchmarkResults:
    """Complete insertion benchmark results."""

    total: int
    results: list[InsertionResult]

    @property
    def correct(self) -> list[InsertionResult]:
        """Get all correct insertions."""
        return [r for r in self.results if r.status == InsertionStatus.CORRECT]

    @property
    def type_mismatch(self) -> list[InsertionResult]:
        """Get all type mismatches."""
        return [r for r in self.results if r.status == InsertionStatus.TYPE_MISMATCH]

    @property
    def insertion_failed(self) -> list[InsertionResult]:
        """Get all insertion failures."""
        return [r for r in self.results if r.status == InsertionStatus.INSERTION_FAILED]

    @property
    def inference_failed(self) -> list[InsertionResult]:
        """Get all inference failures."""
        return [r for r in self.results if r.status == InsertionStatus.INFERENCE_FAILED]

    @property
    def syntax_errors(self) -> list[InsertionResult]:
        """Get all syntax errors."""
        return [r for r in self.results if r.status == InsertionStatus.SYNTAX_ERROR]

    @property
    def annotation_missing(self) -> list[InsertionResult]:
        """Get all cases where annotation is missing."""
        return [r for r in self.results if r.status == InsertionStatus.ANNOTATION_MISSING]

    @property
    def not_applicable(self) -> list[InsertionResult]:
        """Get all not applicable cases."""
        return [r for r in self.results if r.status == InsertionStatus.NOT_APPLICABLE]


def _inference_failed(case: BenchmarkCase, reason: str) -> InsertionResult:
    """Create an InsertionResult for inference failure."""
    return InsertionResult(
        case=case,
        status=InsertionStatus.INFERENCE_FAILED,
        inferred_type=None,
        inserted_source=None,
        insertion_success=False,
        syntax_valid=True,
        type_matches=False,
        reason=reason,
    )


def _handle_simple_variable(
    case: BenchmarkCase,
    inference_result: InferenceResult,
) -> InsertionResult:
    """Handle SIMPLE_VARIABLE cases."""
    if case.variable_name is None:
        return _inference_failed(case, "variable_name missing")

    # Simple variable: Use standard inference with scope tree lookup
    type_info = inference_result.scope_tree.root.get_variable_type_at_line(
        case.variable_name, case.line_number - 1
    )

    if not type_info or type_info.type_str == "Unknown":
        return _inference_failed(case, "Could not infer type for variable")

    inferred_type = type_info.type_str

    # Get insertion engine from DI container
    insertion_engine = get_container().get(UnifiedInsertionEngine)

    # Create target and insert type annotation
    line = _find_variable_line(case.source_code, case.variable_name)
    target = _create_variable_target(case.variable_name, inferred_type, line)
    result = insertion_engine.insert([target], case.source_code)

    # Extract results from unified API
    modified_source = result.modified_source
    insertion_success = result.success

    # Validate the result
    validation = validate_insertion_result(
        case, case.source_code, modified_source, inferred_type, insertion_success
    )

    return _build_result(case, inferred_type, modified_source, insertion_success, validation)


async def _handle_complex_variable(
    case: BenchmarkCase,
) -> InsertionResult:
    """Handle COMPLEX_VARIABLE cases (subscripts, attributes)."""
    if case.variable_name is None:
        return _inference_failed(case, "variable_name missing")

    # Get engines from DI container
    container = get_container()
    inference_engine = container.get(InferenceEngineProtocol)
    insertion_engine = container.get(UnifiedInsertionEngine)

    # Use synthetic query for complex expressions
    inferred_type = await inference_engine.infer_expression_type(
        case.source_code, case.variable_name
    )

    if inferred_type is None:
        return _inference_failed(case, "Could not infer type for complex variable")

    # Create target and insert type annotation
    line = _find_variable_line(case.source_code, case.variable_name)
    target = _create_variable_target(case.variable_name, inferred_type, line)
    result = insertion_engine.insert([target], case.source_code)

    # Extract results from unified API
    modified_source = result.modified_source
    insertion_success = result.success

    # Validate the result
    validation = validate_insertion_result(
        case, case.source_code, modified_source, inferred_type, insertion_success
    )

    return _build_result(case, inferred_type, modified_source, insertion_success, validation)


def _handle_function_return(
    case: BenchmarkCase,
    inference_result: InferenceResult,
) -> InsertionResult:
    """Handle FUNCTION_RETURN cases."""
    if case.function_name is None:
        return _inference_failed(case, "function_name missing")

    # Find function scope
    func_scope = inference_result.scope_tree.get_function_scope_by_qualified_name(
        case.function_name
    )

    if not func_scope or not func_scope.return_type:
        return _inference_failed(case, "Could not find function or infer return type")

    if func_scope.return_type.type_str == "Unknown":
        return _inference_failed(case, "Return type is Unknown")

    inferred_type = func_scope.return_type.type_str

    # Build annotations dict for insert_function_signatures
    function_annotations: dict[str, dict[str, Any]] = {
        case.function_name: {"return": inferred_type}
    }

    # Get insertion engine from DI container
    insertion_engine = get_container().get(UnifiedInsertionEngine)

    # Create function return target
    line = _find_function_line(case.source_code, case.function_name)
    target = InsertionTarget(
        target_type=TargetType.FUNCTION_RETURN,
        location=CodeLocation(line=line, column=0),
        type_annotation=inferred_type,
        name=case.function_name,
    )

    # Insert annotation using unified API
    result = insertion_engine.insert([target], case.source_code)
    modified_source = result.modified_source

    # Validate the result
    insertion_success = result.success and result.inserted_count > 0
    annotation_inserted, annotation_error = verify_function_annotation_inserted(
        modified_source, case.function_name, "return"
    )

    return _build_function_result(
        case,
        inferred_type,
        modified_source,
        insertion_success,
        annotation_inserted,
        annotation_error,
    )


def _handle_function_param(
    case: BenchmarkCase,
    inference_result: InferenceResult,
) -> InsertionResult:
    """Handle FUNCTION_PARAM cases."""
    if case.function_name is None or case.parameter_name is None:
        return _inference_failed(case, "function_name or parameter_name missing")

    # Find function scope
    func_scope = inference_result.scope_tree.get_function_scope_by_qualified_name(
        case.function_name
    )

    if not func_scope or case.parameter_name not in func_scope.parameters:
        return _inference_failed(case, "Could not find parameter in function")

    param_type = func_scope.parameters[case.parameter_name]
    if param_type.type_str == "Unknown":
        return _inference_failed(case, "Parameter type is Unknown")

    inferred_type = param_type.type_str

    # Build annotations dict
    function_annotations: dict[str, dict[str, Any]] = {
        case.function_name: {"params": {case.parameter_name: inferred_type}}
    }

    # Get insertion engine from DI container
    insertion_engine = get_container().get(UnifiedInsertionEngine)

    # Create function parameter target
    line = _find_function_line(case.source_code, case.function_name)
    target = InsertionTarget(
        target_type=TargetType.FUNCTION_PARAMETER,
        location=CodeLocation(line=line, column=0),
        type_annotation=inferred_type,
        name=case.parameter_name,
        metadata={"function_name": case.function_name},
    )

    # Insert annotation using unified API
    result = insertion_engine.insert([target], case.source_code)
    modified_source = result.modified_source

    # Validate the result
    insertion_success = result.success and result.inserted_count > 0
    annotation_inserted, annotation_error = verify_function_annotation_inserted(
        modified_source, case.function_name, "param", case.parameter_name
    )

    return _build_function_result(
        case,
        inferred_type,
        modified_source,
        insertion_success,
        annotation_inserted,
        annotation_error,
    )


def _build_result(
    case: BenchmarkCase,
    inferred_type: str,
    modified_source: str,
    insertion_success: bool,
    validation: dict[str, Any],
) -> InsertionResult:
    """Build InsertionResult from validation results."""
    if not insertion_success:
        status = InsertionStatus.INSERTION_FAILED
        reason = validation.get("insertion_error")
    elif not validation["syntax_valid"]:
        status = InsertionStatus.SYNTAX_ERROR
        reason = validation.get("syntax_error")
    elif not validation["annotation_inserted"]:
        status = InsertionStatus.ANNOTATION_MISSING
        reason = validation.get("insertion_error")
    elif not validation["type_matches"]:
        status = InsertionStatus.TYPE_MISMATCH
        reason = validation.get("type_match_info")
    else:
        status = InsertionStatus.CORRECT
        reason = None

    return InsertionResult(
        case=case,
        status=status,
        inferred_type=inferred_type,
        inserted_source=modified_source if insertion_success else None,
        insertion_success=insertion_success,
        syntax_valid=validation["syntax_valid"],
        type_matches=validation["type_matches"],
        reason=reason,
    )


def _build_function_result(
    case: BenchmarkCase,
    inferred_type: str,
    modified_source: str,
    insertion_success: bool,
    annotation_inserted: bool,
    annotation_error: str | None,
) -> InsertionResult:
    """Build InsertionResult for function annotation cases."""
    from tests.benchmarks.insertion.validator import validate_syntax, validate_type_match

    syntax_valid, syntax_error = validate_syntax(modified_source)
    type_matches = validate_type_match(inferred_type, case.expected_types)

    reason: str | None
    if not insertion_success:
        status = InsertionStatus.INSERTION_FAILED
        reason = "InsertionEngine failed to insert annotation"
    elif not syntax_valid:
        status = InsertionStatus.SYNTAX_ERROR
        reason = syntax_error
    elif not annotation_inserted:
        status = InsertionStatus.ANNOTATION_MISSING
        reason = annotation_error
    elif not type_matches:
        status = InsertionStatus.TYPE_MISMATCH
        reason = f"'{inferred_type}' does not match expected {case.expected_types}"
    else:
        status = InsertionStatus.CORRECT
        reason = None

    return InsertionResult(
        case=case,
        status=status,
        inferred_type=inferred_type,
        inserted_source=modified_source if insertion_success else None,
        insertion_success=insertion_success,
        syntax_valid=syntax_valid,
        type_matches=type_matches,
        reason=reason,
    )


async def run_insertion_on_case(
    case: BenchmarkCase,
) -> InsertionResult:
    """Run insertion workflow on a single benchmark case.

    Workflow:
    1. Use JediInferenceEngine to infer the type based on annotation type
    2. Use InsertionEngine to insert the type annotation
    3. Validate the result (syntax, type match, annotation presence)
    4. Categorize the outcome

    Uses the same TypeAnnotationWorkflow as the LSP server
    to ensure consistent behavior.

    Args:
        case: Benchmark case to process

    Returns:
        InsertionResult with status and details
    """
    # Get workflow from DI container
    workflow = get_container().get(TypeAnnotationWorkflowProtocol)

    # Run inference using the same workflow as LSP server
    inference_result, _, _ = await workflow.infer_and_collect_types(
        case.source_code, str(case.file_path)
    )

    # Dispatch based on annotation type
    match case.annotation_type:
        case AnnotationType.SIMPLE_VARIABLE:
            return _handle_simple_variable(case, inference_result)

        case AnnotationType.COMPLEX_VARIABLE:
            return await _handle_complex_variable(case)

        case AnnotationType.SUBSCRIPT_ACCESS:
            # Subscript access (d['a'], list[0]) cannot be annotated inline in Python
            return InsertionResult(
                case=case,
                status=InsertionStatus.NOT_APPLICABLE,
                inferred_type=None,
                inserted_source=None,
                insertion_success=False,
                syntax_valid=True,
                type_matches=False,
                reason=f"Subscript access '{case.variable_name}' cannot be annotated inline",
            )

        case AnnotationType.ATTRIBUTE_ACCESS:
            # Attribute access (self.width, obj.attr) cannot be annotated inline in Python
            return InsertionResult(
                case=case,
                status=InsertionStatus.NOT_APPLICABLE,
                inferred_type=None,
                inserted_source=None,
                insertion_success=False,
                syntax_valid=True,
                type_matches=False,
                reason=f"Attribute access '{case.variable_name}' cannot be annotated inline",
            )

        case AnnotationType.ITERATION_VARIABLE:
            # Loop iteration variables (for i in ...) cannot be annotated inline in Python
            return InsertionResult(
                case=case,
                status=InsertionStatus.NOT_APPLICABLE,
                inferred_type=None,
                inserted_source=None,
                insertion_success=False,
                syntax_valid=True,
                type_matches=False,
                reason=f"Iteration variable '{case.variable_name}' cannot be annotated inline",
            )

        case AnnotationType.FUNCTION_RETURN:
            return _handle_function_return(case, inference_result)

        case AnnotationType.FUNCTION_PARAM:
            return _handle_function_param(case, inference_result)

        case _:
            return InsertionResult(
                case=case,
                status=InsertionStatus.NOT_APPLICABLE,
                inferred_type=None,
                inserted_source=None,
                insertion_success=False,
                syntax_valid=True,
                type_matches=False,
                reason=f"Unsupported annotation type: {case.annotation_type.value}",
            )


def run_insertion_benchmark(
    cases: list[BenchmarkCase],
    show_progress: bool = True,
) -> InsertionBenchmarkResults:
    """Run insertion benchmark on all cases with progress indicator.

    Uses the DI container to get workflow and engine instances.

    Args:
        cases: List of benchmark cases to process
        show_progress: Whether to show progress updates

    Returns:
        InsertionBenchmarkResults with all results
    """
    results = []
    total = len(cases)

    for i, case in enumerate(cases, 1):
        if show_progress and i % 50 == 0:
            print(f"Progress: [{i}/{total}] ({i / total * 100:.1f}%)")

        result = asyncio.run(run_insertion_on_case(case))
        results.append(result)

    if show_progress:
        print(f"Progress: [{total}/{total}] (100.0%)")

    return InsertionBenchmarkResults(total=total, results=results)
