"""Tests for benchmark expression resolver fallback logic."""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from auto_type.inference.jedi_engine import JediInferenceEngine
from benchmark.typeevalpy.expression_resolver import resolve_expression_type
from benchmark.typeevalpy.loader import BenchmarkCase, load_benchmark


def _find_case(
    cases: list[BenchmarkCase],
    category: str,
    variable_name: str,
) -> BenchmarkCase:
    for case in cases:
        if case.category == category and case.variable_name == variable_name:
            return case
    msg = f"Case not found: {category} / {variable_name}"
    raise AssertionError(msg)


def test_resolve_self_attribute_from_scope_attributes() -> None:
    cases = load_benchmark()
    case = _find_case(cases, "python_features/classes/abstract_class", "self.width")

    engine = JediInferenceEngine()
    result = engine.infer_types(
        case.source_code,
        path=str(case.file_path),
        project_root=str(case.project_root) if case.project_root else None,
    )

    inferred = resolve_expression_type(case, result)
    assert inferred == "int"


def test_resolve_self_attribute_assigned_from_method_reference() -> None:
    cases = load_benchmark()
    case = _find_case(cases, "python_features/classes/self_assignment", "self.smth")

    engine = JediInferenceEngine()
    result = engine.infer_types(
        case.source_code,
        path=str(case.file_path),
        project_root=str(case.project_root) if case.project_root else None,
    )

    inferred = resolve_expression_type(case, result)
    assert inferred == "Callable"


def test_resolve_self_attribute_from_class_context() -> None:
    cases = load_benchmark()
    case = _find_case(cases, "python_features/generators/iter_param", "self.n")

    engine = JediInferenceEngine()
    result = engine.infer_types(
        case.source_code,
        path=str(case.file_path),
        project_root=str(case.project_root) if case.project_root else None,
    )

    inferred = resolve_expression_type(case, result)
    assert inferred == "int"


def test_resolve_subscript_from_generic_container() -> None:
    cases = load_benchmark()
    case = _find_case(cases, "python_features/generators/iter_param", "output_list[0]")

    engine = JediInferenceEngine()
    result = engine.infer_types(
        case.source_code,
        path=str(case.file_path),
        project_root=str(case.project_root) if case.project_root else None,
    )

    inferred = resolve_expression_type(case, result)
    assert inferred == "int"


def test_resolve_subscript_from_dict_merge_assignment() -> None:
    cases = load_benchmark()
    case = _find_case(cases, "python_features/dicts/merge", "merged_dict['a']")

    engine = JediInferenceEngine()
    result = engine.infer_types(
        case.source_code,
        path=str(case.file_path),
        project_root=str(case.project_root) if case.project_root else None,
    )

    inferred = resolve_expression_type(case, result)
    assert inferred == "int"


def test_resolve_subscript_from_starred_assignment() -> None:
    cases = load_benchmark()
    case = _find_case(cases, "python_features/assignments/starred", "b[0]")

    engine = JediInferenceEngine()
    result = engine.infer_types(
        case.source_code,
        path=str(case.file_path),
        project_root=str(case.project_root) if case.project_root else None,
    )

    inferred = resolve_expression_type(case, result)
    assert inferred == "Callable"


def test_resolver_returns_none_for_unknown_expression() -> None:
    cases = load_benchmark()
    case = _find_case(cases, "python_features/dicts/merge", "merged_dict['a']")
    modified = BenchmarkCase(
        file_path=case.file_path,
        source_code=case.source_code,
        line_number=case.line_number,
        col_offset=case.col_offset,
        variable_name="does_not_exist[0]",
        function_name=case.function_name,
        parameter_name=case.parameter_name,
        expected_types=case.expected_types,
        category=case.category,
        annotation_type=case.annotation_type,
        project_root=case.project_root,
    )

    engine = JediInferenceEngine()
    result = engine.infer_types(
        modified.source_code,
        path=str(modified.file_path),
        project_root=str(modified.project_root) if modified.project_root else None,
    )

    assert resolve_expression_type(modified, result) is None
