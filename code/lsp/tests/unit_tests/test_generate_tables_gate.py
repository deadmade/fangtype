"""Tests for the thesis evaluation exporter's gate-transition macro source.

``thesis/evaluation/generate_tables.py`` is not part of the ``fangtype``/``benchmark``
package tree, so it carries no type stubs and is reached the same way
``benchmark/typeevalpy/official.py`` reaches the vendored TypeEvalPy scorer, namely a
``sys.path`` insert plus a ``# noqa: E402`` import.

``gate_transitions`` computes the four ``\\evalMypyGate*`` macros the thesis cites in
prose, from a per-target transition matrix between a gate-on and a gate-off mypy-insert
run. It had no test before this file, so a join-key or status-branch mistake would
silently publish a wrong number rather than fail a test.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_EVAL_DIR = Path(__file__).resolve().parents[4] / "thesis" / "evaluation"
if str(_EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(_EVAL_DIR))

import generate_tables  # noqa: E402


def _target(
    *,
    path: str = "mod.py",
    line: int = 1,
    ident: str = "f.return",
    kind: str = "function_return",
    status: str,
) -> dict:
    return {
        "relative_path": path,
        "line_number": line,
        "identifier": ident,
        "target_kind": kind,
        "status": status,
    }


def _file_result(
    *,
    path: str = "mod.py",
    inferred: dict[str, int] | None = None,
    correct: dict[str, int] | None = None,
) -> dict:
    # gate_transitions' drift check reads only these three keys off a file result, via
    # the inferred()/correct() helpers closed over inside it.
    return {
        "relative_path": path,
        "inferred_distinct_by_category": inferred or {"function_returns": 9},
        "correct_distinct_by_category": correct or {"function_returns": 3},
    }


def _artefact(targets: list[dict], file_results: list[dict] | None = None) -> dict:
    # gate_transitions always reads file_results for its drift computation, even when a
    # test only asserts on the target-level transition counts, so every artefact needs
    # one. The default is identical on both sides of a fixture pair unless overridden,
    # which keeps that pair drift-free.
    return {
        "target_results": targets,
        "file_results": file_results if file_results is not None else [_file_result()],
    }


class TestGateTransitions:
    """A small, fully-known transition matrix pins the four macro values exactly."""

    def _fixture(self) -> tuple[dict, dict]:
        # Eight targets, each a distinct (path, line, identifier, kind) key shared by
        # both artefacts. Only the status differs between the gate-on and gate-off run.
        specs = [
            # (identifier, on_status, off_status)
            ("unchanged_not_inserted", "not_inserted", "not_inserted"),
            ("unchanged_wrong", "inserted_wrong", "inserted_wrong"),
            ("unchanged_correct", "inserted_correct", "inserted_correct"),
            ("blocked_wrong_1", "not_inserted", "inserted_wrong"),
            ("blocked_wrong_2", "not_inserted", "inserted_wrong"),
            ("blocked_correct_1", "not_inserted", "inserted_correct"),
            ("admitted_wrong_1", "inserted_wrong", "not_inserted"),
            ("admitted_correct_1", "inserted_correct", "not_inserted"),
            # Cross transition between the two "inserted" states. Neither blocked nor
            # admitted by gate_transitions' definition, since neither side is
            # not_inserted -- must not leak into either bucket.
            ("cross_wrong_to_correct", "inserted_correct", "inserted_wrong"),
        ]
        on_targets = [_target(ident=ident, status=on) for ident, on, _off in specs]
        off_targets = [_target(ident=ident, status=off) for ident, _on, off in specs]
        return _artefact(on_targets), _artefact(off_targets)

    def test_blocked_counts_and_precision(self) -> None:
        insert, insert_nogate = self._fixture()

        result = generate_tables.gate_transitions(insert, insert_nogate)

        assert result["blocked_wrong"] == 2
        assert result["blocked_correct"] == 1
        assert result["blocked"] == 3
        assert result["precision_pct"] == generate_tables._pct(2, 3)

    def test_admitted_counts_are_tracked_separately_from_blocked(self) -> None:
        insert, insert_nogate = self._fixture()

        result = generate_tables.gate_transitions(insert, insert_nogate)

        assert result["admitted_wrong"] == 1
        assert result["admitted_correct"] == 1

    def test_cross_and_unchanged_targets_affect_neither_bucket(self) -> None:
        """The wrong<->correct cross transition is real in the committed artefacts too."""
        insert, insert_nogate = self._fixture()

        result = generate_tables.gate_transitions(insert, insert_nogate)

        # 9 targets total, 3 blocked + 2 admitted leaves 4 that are neither.
        counted = result["blocked"] + result["admitted_wrong"] + result["admitted_correct"]
        assert counted == 5

    def test_mismatched_target_sets_raise(self) -> None:
        insert = _artefact([_target(ident="only_in_insert", status="not_inserted")])
        insert_nogate = _artefact([_target(ident="only_in_nogate", status="not_inserted")])

        with pytest.raises(SystemExit):
            generate_tables.gate_transitions(insert, insert_nogate)

    def test_reproduces_the_committed_artefact_pair(self) -> None:
        """Run against the committed JSON, asserting what a re-run cannot change.

        The exact counts move whenever the artefacts are re-measured, so pinning them
        made this test fail on every honest re-run and say nothing about the function.
        What must hold for any artefact pair is the split and the percentage derived
        from it, so those are what is checked. The published counts themselves are
        guarded where they belong, in ``generate_tables``' own consistency checks and
        the macros it emits.
        """
        insert = generate_tables._load("mypy_insert.json", gate_enabled=True)
        insert_nogate = generate_tables._load("mypy_insert_nogate.json", gate_enabled=False)

        result = generate_tables.gate_transitions(insert, insert_nogate)

        assert result["blocked"] > 0
        assert result["blocked"] == result["blocked_wrong"] + result["blocked_correct"]
        expected_pct = f"{result['blocked_wrong'] / result['blocked'] * 100:.1f}"
        assert result["precision_pct"] == expected_pct
