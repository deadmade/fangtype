"""Unit tests for unified benchmark CLI entrypoint."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import benchmark.run_benchmark as cli_module


def test_main_defaults_to_inference_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default invocation should run inference mode."""
    cases = [SimpleNamespace(category="lists/basic"), SimpleNamespace(category="dicts/basic")]
    results = object()

    load_benchmark_mock = MagicMock(return_value=cases)
    run_inference_mock = MagicMock(return_value=results)
    generate_report_mock = MagicMock(return_value="inference-report")

    monkeypatch.setattr(cli_module, "load_benchmark", load_benchmark_mock)
    monkeypatch.setattr(cli_module, "run_inference_benchmark", run_inference_mock)
    monkeypatch.setattr(cli_module, "generate_inference_report", generate_report_mock)
    monkeypatch.setattr(cli_module, "export_inference_json", MagicMock())
    monkeypatch.setattr(sys, "argv", ["run_benchmark.py"])

    exit_code = cli_module.main()

    assert exit_code == 0
    load_benchmark_mock.assert_called_once_with()
    run_inference_mock.assert_called_once_with(cases, show_progress=True)
    generate_report_mock.assert_called_once_with(results)


def test_main_insertion_mode_applies_filter_and_max_cases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Insertion mode should filter category and apply max case limit."""
    cases = [
        SimpleNamespace(category="lists/simple"),
        SimpleNamespace(category="lists/nested"),
        SimpleNamespace(category="dicts/simple"),
    ]
    results = object()

    run_insertion_mock = MagicMock(return_value=results)
    export_json_mock = MagicMock()
    export_failures_mock = MagicMock()

    monkeypatch.setattr(cli_module, "load_insertable_cases", MagicMock(return_value=cases))
    monkeypatch.setattr(cli_module, "run_insertion_benchmark", run_insertion_mock)
    monkeypatch.setattr(cli_module, "generate_insertion_report", MagicMock(return_value="report"))
    monkeypatch.setattr(cli_module, "export_insertion_json", export_json_mock)
    monkeypatch.setattr(cli_module, "export_failed_cases", export_failures_mock)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_benchmark.py",
            "--mode",
            "insertion",
            "--category",
            "lists",
            "--max-cases",
            "1",
            "--output",
            "/tmp/results.json",
            "--export-failures",
            "/tmp/failures",
            "--no-progress",
        ],
    )

    exit_code = cli_module.main()

    assert exit_code == 0
    run_insertion_mock.assert_called_once()
    called_cases = run_insertion_mock.call_args.args[0]
    assert len(called_cases) == 1
    assert called_cases[0].category.startswith("lists/")
    assert run_insertion_mock.call_args.kwargs["show_progress"] is False
    export_json_mock.assert_called_once_with(results, Path("/tmp/results.json"))
    export_failures_mock.assert_called_once_with(results, Path("/tmp/failures"))


def test_mode_specific_flags_are_rejected_for_inference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Insertion-only flags should raise argparse error in inference mode."""
    monkeypatch.setattr(
        sys, "argv", ["run_benchmark.py", "--mode", "inference", "--max-cases", "5"]
    )

    with pytest.raises(SystemExit) as exc_info:
        cli_module.main()

    assert exc_info.value.code == 2


def test_no_category_matches_returns_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Category mismatch should exit with error before runner starts."""
    cases = [SimpleNamespace(category="dicts/simple")]
    run_inference_mock = MagicMock()

    monkeypatch.setattr(cli_module, "load_benchmark", MagicMock(return_value=cases))
    monkeypatch.setattr(cli_module, "run_inference_benchmark", run_inference_mock)
    monkeypatch.setattr(sys, "argv", ["run_benchmark.py", "--category", "lists"])

    exit_code = cli_module.main()

    assert exit_code == 1
    run_inference_mock.assert_not_called()
