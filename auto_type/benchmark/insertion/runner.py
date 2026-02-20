"""Run insertion benchmark by delegating insertion logic to production workflow.

Benchmark responsibilities in this module are limited to:
- loading benchmark cases into workflow requests,
- invoking production workflow APIs,
- validating and categorizing outcomes.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Any

from auto_type.container import get_container
from auto_type.insertion import (
    InsertionTarget,
    create_variable_target,
    detect_assignment_pattern,
    find_function_line,
    find_variable_line,
)
from auto_type.protocols import TypeAnnotationWorkflowProtocol
from benchmark.insertion.validator import (
    validate_insertion_result,
    verify_function_annotation_inserted,
)
from benchmark.typeevalpy.loader import AnnotationType, BenchmarkCase


class InsertionStatus(Enum):
    """Status of insertion benchmark result."""

    CORRECT = "correct"
    TYPE_MISMATCH = "type_mismatch"
    INSERTION_FAILED = "insertion_failed"
    INFERENCE_FAILED = "inference_failed"
    SYNTAX_ERROR = "syntax_error"
    ANNOTATION_MISSING = "annotation_missing"
    NOT_APPLICABLE = "not_applicable"


@dataclass
class InsertionResult:
    """Result of running insertion on one benchmark case."""

    case: BenchmarkCase
    status: InsertionStatus
    inferred_type: str | None
    inserted_source: str | None
    insertion_success: bool
    syntax_valid: bool
    type_matches: bool
    reason: str | None


@dataclass
class InsertionBenchmarkResults:
    """Complete insertion benchmark results."""

    total: int
    results: list[InsertionResult]

    @property
    def correct(self) -> list[InsertionResult]:
        return [r for r in self.results if r.status == InsertionStatus.CORRECT]

    @property
    def type_mismatch(self) -> list[InsertionResult]:
        return [r for r in self.results if r.status == InsertionStatus.TYPE_MISMATCH]

    @property
    def insertion_failed(self) -> list[InsertionResult]:
        return [r for r in self.results if r.status == InsertionStatus.INSERTION_FAILED]

    @property
    def inference_failed(self) -> list[InsertionResult]:
        return [r for r in self.results if r.status == InsertionStatus.INFERENCE_FAILED]

    @property
    def syntax_errors(self) -> list[InsertionResult]:
        return [r for r in self.results if r.status == InsertionStatus.SYNTAX_ERROR]

    @property
    def annotation_missing(self) -> list[InsertionResult]:
        return [r for r in self.results if r.status == InsertionStatus.ANNOTATION_MISSING]

    @property
    def not_applicable(self) -> list[InsertionResult]:
        return [r for r in self.results if r.status == InsertionStatus.NOT_APPLICABLE]


def _inference_failed(case: BenchmarkCase, reason: str) -> InsertionResult:
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


def _build_result(
    case: BenchmarkCase,
    inferred_type: str,
    modified_source: str,
    insertion_success: bool,
    validation: dict[str, Any],
) -> InsertionResult:
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
    from benchmark.insertion.validator import validate_syntax, validate_type_match

    syntax_valid, syntax_error = validate_syntax(modified_source)
    type_matches = validate_type_match(inferred_type, case.expected_types)

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


async def run_insertion_on_case(case: BenchmarkCase) -> InsertionResult:
    """Run insertion workflow on a single benchmark case via production workflow."""
    workflow = get_container().get(TypeAnnotationWorkflowProtocol)
    project_root = str(case.project_root) if case.project_root else None

    result = await workflow.annotate_target_with_fallbacks(
        source=case.source_code,
        file_path=str(case.file_path),
        line_number=case.line_number,
        annotation_type=case.annotation_type.value,
        variable_name=case.variable_name,
        function_name=case.function_name,
        parameter_name=case.parameter_name,
        project_root=project_root,
    )

    inferred_type = result.get("inferred_type")
    if inferred_type is None:
        return _inference_failed(case, str(result.get("error_message") or "Could not infer type"))

    modified_source = str(result.get("modified_source") or case.source_code)
    insertion_success = bool(result.get("insertion_success"))

    if case.annotation_type in {AnnotationType.FUNCTION_RETURN, AnnotationType.FUNCTION_PARAM}:
        if case.function_name is None:
            return _inference_failed(case, "function_name missing")

        if case.annotation_type == AnnotationType.FUNCTION_RETURN:
            annotation_inserted, annotation_error = verify_function_annotation_inserted(
                modified_source, case.function_name, "return"
            )
        else:
            annotation_inserted, annotation_error = verify_function_annotation_inserted(
                modified_source,
                case.function_name,
                "param",
                case.parameter_name,
            )

        return _build_function_result(
            case,
            str(inferred_type),
            modified_source,
            insertion_success,
            annotation_inserted,
            annotation_error,
        )

    validation = validate_insertion_result(
        case,
        case.source_code,
        modified_source,
        str(inferred_type),
        insertion_success,
    )
    return _build_result(case, str(inferred_type), modified_source, insertion_success, validation)


async def _run_insertion_benchmark_async(
    cases: list[BenchmarkCase],
    show_progress: bool = True,
) -> InsertionBenchmarkResults:
    """Run insertion benchmark asynchronously over all cases."""
    total = len(cases)

    async def process_case(case: BenchmarkCase) -> InsertionResult:
        return await run_insertion_on_case(case)

    if show_progress:
        print(f"Processing {total} cases...")

    results = await asyncio.gather(*[process_case(case) for case in cases])
    return InsertionBenchmarkResults(total=total, results=list(results))


def run_insertion_benchmark(
    cases: list[BenchmarkCase],
    show_progress: bool = True,
) -> InsertionBenchmarkResults:
    """Run insertion benchmark synchronously."""
    return asyncio.run(_run_insertion_benchmark_async(cases, show_progress))


# Backward-compatible helpers used by tests.
def _create_variable_target_for_case(
    source: str,
    name: str,
    type_annotation: str,
    line_hint_0: int | None = None,
    line_fallback_1: int | None = None,
) -> InsertionTarget:
    """Create insertion target mirroring production assignment resolution."""
    line = line_fallback_1 if line_fallback_1 is not None else find_variable_line(source, name)
    if line_hint_0 is not None and line_fallback_1 is None:
        line = line_hint_0 if line_hint_0 > 0 else line
    target_type = detect_assignment_pattern(source, name, line - 1)
    return create_variable_target(name, type_annotation, line, target_type=target_type)


def _resolve_function_target(source: str, function_name: str) -> tuple[int, str]:
    """Resolve function target line and unqualified function name for insertion."""
    line = find_function_line(source, function_name)
    simple_name = function_name.split(".")[-1]
    return line, simple_name
