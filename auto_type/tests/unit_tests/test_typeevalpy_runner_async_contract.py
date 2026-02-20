"""Regression tests for sync infer_expression_type usage in TypeEvalPy runner."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from benchmark.typeevalpy.loader import AnnotationType, BenchmarkCase
from benchmark.typeevalpy.runner import ResultStatus, run_inference_on_case


@pytest.mark.parametrize(
    "annotation_type",
    [
        AnnotationType.COMPLEX_VARIABLE,
        AnnotationType.SUBSCRIPT_ACCESS,
        AnnotationType.ATTRIBUTE_ACCESS,
    ],
)
def test_run_inference_on_case_expression_types_use_sync_inference(
    annotation_type: AnnotationType, monkeypatch
) -> None:
    """Expression-based annotation cases should not await sync inference results."""
    import benchmark.typeevalpy.runner as runner_module

    case = BenchmarkCase(
        file_path=Path("/tmp/test.py"),
        source_code="x = unknown_value()\n",
        line_number=1,
        col_offset=0,
        variable_name="x",
        function_name=None,
        parameter_name=None,
        expected_types=["int"],
        category="test",
        annotation_type=annotation_type,
    )

    mock_workflow = MagicMock()
    mock_workflow.infer_and_collect_types = AsyncMock(return_value=(MagicMock(), {}, {}))

    mock_inference_engine = MagicMock()
    mock_inference_engine.infer_expression_type.return_value = "int"

    monkeypatch.setattr(runner_module, "resolve_expression_type", lambda *_args, **_kwargs: None)

    inference_result = asyncio.run(
        run_inference_on_case(case, mock_workflow, mock_inference_engine)
    )

    assert inference_result.status == ResultStatus.CORRECT
    assert inference_result.inferred_type == "int"
