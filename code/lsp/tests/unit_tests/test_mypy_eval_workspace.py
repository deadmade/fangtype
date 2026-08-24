"""Tests for the evaluation harness's workspace layout and artefact labelling.

Two properties matter here. A gate-on and a gate-off run must not share a resume
journal, because they measure different pipelines. And an exported artefact must name
the configuration that produced it, because the gate-on and gate-off JSONs are otherwise
schema-identical and are told apart only by the filename an operator types.

These drive a two-file temporary corpus rather than the mypy submodule, so they run in
the ordinary gate without a submodule checkout.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from benchmark import run_benchmark
from benchmark.mypy_eval import prepare as prepare_mod
from benchmark.mypy_eval.insertion_runner import MypyInsertionResults
from benchmark.mypy_eval.prepare import (
    get_prepared_dir,
    get_run_dir,
    prepare_mypy_workspace,
)
from benchmark.mypy_eval.reporter import export_insertion_json
from benchmark.mypy_eval.reporter import export_json as export_mypy_json
from benchmark.mypy_eval.runner import MypyBenchmarkResults, MypyGroupSummary
from benchmark.typeevalpy.inference_runner import InferenceScore
from benchmark.typeevalpy.reporter import export_json as export_inference_json

if TYPE_CHECKING:
    from collections.abc import Callable

TYPED_SOURCE = "def f(x: int) -> str:\n    y: int = 1\n    return str(x) + str(y)\n"
UNTYPED_SOURCE = "def g(z):\n    return z\n"


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    """A minimal stand-in for the mypy source tree, one typed file and one untyped."""
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "typed.py").write_text(TYPED_SOURCE, encoding="utf-8")
    (root / "untyped.py").write_text(UNTYPED_SOURCE, encoding="utf-8")
    return root


@pytest.fixture
def prepared(tmp_path: Path) -> Path:
    return tmp_path / "prepared"


class TestRunDirectories:
    """The run directory is what keeps two configurations' journals apart."""

    def test_gate_states_get_separate_directories(self, tmp_path: Path) -> None:
        on = get_run_dir("jedi", gate_enabled=True, root=tmp_path)
        off = get_run_dir("jedi", gate_enabled=False, root=tmp_path)

        assert on != off
        assert on.is_dir()
        assert off.is_dir()

    def test_resolution_contexts_get_separate_directories(self, tmp_path: Path) -> None:
        """A shared journal would replay the annotated arm under the cold arm's name.

        The two contexts score the same targets from byte-identical text, so a replayed
        journal would not look wrong. It would make the pair agree perfectly, which is
        the one result the comparison cannot be allowed to manufacture.
        """
        annotated = get_run_dir("jedi", gate_enabled=True, root=tmp_path)
        cold = get_run_dir("jedi", gate_enabled=True, cold_start=True, root=tmp_path)

        assert annotated != cold
        assert cold.is_dir()

    def test_resolution_context_and_gate_state_both_key_the_directory(self, tmp_path: Path) -> None:
        dirs = {
            get_run_dir("jedi", gate_enabled=gate, cold_start=cold, root=tmp_path)
            for gate in (True, False)
            for cold in (True, False)
        }

        assert len(dirs) == 4

    def test_engines_get_separate_directories(self, tmp_path: Path) -> None:
        assert get_run_dir("jedi", gate_enabled=True, root=tmp_path) != get_run_dir(
            "other", gate_enabled=True, root=tmp_path
        )

    def test_run_directory_is_outside_the_prepared_tree(self, tmp_path: Path) -> None:
        """A preparation rebuild wipes prepared/, so a journal under it would not survive."""
        run_dir = get_run_dir("jedi", gate_enabled=True, root=tmp_path)

        assert get_prepared_dir(tmp_path) not in run_dir.parents

    def test_journal_names_differ_by_gate_state(self, tmp_path: Path) -> None:
        """The two mypy modes' journals, resolved the way run_benchmark resolves them."""
        on = get_run_dir("jedi", gate_enabled=True, root=tmp_path) / "journal_insertion.jsonl"
        off = get_run_dir("jedi", gate_enabled=False, root=tmp_path) / "journal_insertion.jsonl"

        assert on != off


class TestPreparationReuse:
    """Stripping the corpus is configuration-independent, so it is done once."""

    def test_first_run_builds_and_reports_it(self, prepared: Path, corpus: Path) -> None:
        result = prepare_mypy_workspace(prepared, mypy_dir=corpus)

        assert result.reused is False
        assert result.total_python_files == 2
        assert result.typed_file_count == 1
        assert result.untyped_file_count == 1

    def test_stripped_tree_has_annotations_removed(self, prepared: Path, corpus: Path) -> None:
        prepare_mypy_workspace(prepared, mypy_dir=corpus)

        stripped = (prepared / "stripped" / "typed.py").read_text(encoding="utf-8")
        assert "int" not in stripped
        assert (prepared / "original" / "typed.py").read_text(encoding="utf-8") == TYPED_SOURCE

    def test_second_run_reuses_the_tree(self, prepared: Path, corpus: Path) -> None:
        first = prepare_mypy_workspace(prepared, mypy_dir=corpus)
        second = prepare_mypy_workspace(prepared, mypy_dir=corpus)

        assert second.reused is True
        assert _annotations(second) == _annotations(first)
        assert second.total_python_files == first.total_python_files
        assert second.typed_file_count == first.typed_file_count

    def test_reuse_does_not_rewrite_the_tree(self, prepared: Path, corpus: Path) -> None:
        prepare_mypy_workspace(prepared, mypy_dir=corpus)
        stamped = (prepared / "stripped" / "typed.py").stat().st_mtime_ns

        prepare_mypy_workspace(prepared, mypy_dir=corpus)

        assert (prepared / "stripped" / "typed.py").stat().st_mtime_ns == stamped

    def test_force_rebuilds(self, prepared: Path, corpus: Path) -> None:
        prepare_mypy_workspace(prepared, mypy_dir=corpus)

        assert prepare_mypy_workspace(prepared, mypy_dir=corpus, force=True).reused is False

    def test_manifest_omits_the_run_local_reuse_flag(self, prepared: Path, corpus: Path) -> None:
        prepare_mypy_workspace(prepared, mypy_dir=corpus)

        payload = json.loads((prepared / "manifest.json").read_text(encoding="utf-8"))
        assert "reused" not in payload


class TestColdStartTree:
    """The cold tree exists so that a stripped corpus is still an importable package."""

    def test_cold_tree_nests_under_the_corpus_package_name(
        self, prepared: Path, corpus: Path
    ) -> None:
        """``import corpus.typed`` has to resolve inside the tree, so the root is its parent."""
        result = prepare_mypy_workspace(prepared, mypy_dir=corpus)

        cold = Path(result.coldstart_dir)
        assert cold.name == corpus.name
        assert (cold / "typed.py").is_file()
        assert cold.parent == prepared / "coldstart"

    def test_flat_stripped_tree_could_not_serve_as_the_import_root(
        self, prepared: Path, corpus: Path
    ) -> None:
        """Regression guard for the confound the cold tree exists to avoid.

        Pointing the cold arm at ``stripped/`` would leave no directory named after the
        corpus package anywhere on the path, so every cross-module import would fail to
        resolve. That measures a missing module, not a missing annotation.
        """
        result = prepare_mypy_workspace(prepared, mypy_dir=corpus)

        stripped = Path(result.stripped_dir)
        assert not (stripped.parent / corpus.name).exists()
        assert (Path(result.coldstart_dir).parent / corpus.name).is_dir()

    def test_cold_tree_carries_the_same_text_as_the_stripped_tree(
        self, prepared: Path, corpus: Path
    ) -> None:
        """Both arms feed inference the same document; only the surrounding tree differs."""
        result = prepare_mypy_workspace(prepared, mypy_dir=corpus)

        stripped = (Path(result.stripped_dir) / "typed.py").read_text(encoding="utf-8")
        cold = (Path(result.coldstart_dir) / "typed.py").read_text(encoding="utf-8")
        assert cold == stripped
        assert "int" not in cold

    def test_cold_tree_survives_reuse(self, prepared: Path, corpus: Path) -> None:
        first = prepare_mypy_workspace(prepared, mypy_dir=corpus)
        second = prepare_mypy_workspace(prepared, mypy_dir=corpus)

        assert second.reused is True
        assert second.coldstart_dir == first.coldstart_dir
        assert (Path(second.coldstart_dir) / "typed.py").is_file()


class TestColdStartFlagValidation:
    """``--cold-start`` only means anything to the restore runner."""

    @pytest.mark.parametrize("mode", ["inference", "insertion", "mypy-insert"])
    def test_rejected_outside_restore_mode(self, mode: str) -> None:
        """Accepting it elsewhere would run the ordinary configuration under a cold label."""
        parser = run_benchmark.build_parser()
        args = parser.parse_args(["--mode", mode, "--cold-start"])

        with pytest.raises(SystemExit):
            run_benchmark._validate_mode_specific_args(args, parser)

    def test_accepted_for_restore_mode(self) -> None:
        parser = run_benchmark.build_parser()
        args = parser.parse_args(["--mode", "mypy", "--cold-start"])

        run_benchmark._validate_mode_specific_args(args, parser)

        assert args.cold_start is True


class TestPreparationInvalidation:
    """A stale stripped tree would silently publish ground truth that no longer holds."""

    def test_added_corpus_file_invalidates(self, prepared: Path, corpus: Path) -> None:
        prepare_mypy_workspace(prepared, mypy_dir=corpus)
        (corpus / "extra.py").write_text(
            "def h(w: bool) -> bool:\n    return w\n", encoding="utf-8"
        )

        result = prepare_mypy_workspace(prepared, mypy_dir=corpus)

        assert result.reused is False
        assert result.total_python_files == 3

    def test_changed_stripping_logic_invalidates(
        self, prepared: Path, corpus: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Editing RemovalEngine changes the targets while the corpus stays put."""
        prepare_mypy_workspace(prepared, mypy_dir=corpus)
        monkeypatch.setattr(prepare_mod, "_stripping_fingerprint", lambda: "different")

        assert prepare_mypy_workspace(prepared, mypy_dir=corpus).reused is False

    def test_older_workspace_layout_invalidates(self, prepared: Path, corpus: Path) -> None:
        """A tree prepared before coldstart/ existed must rebuild rather than be reused.

        The stripping is unchanged by a layout move, so ``_stripping_fingerprint`` cannot
        see it and the corpus revision cannot either. Without the layout key such a tree
        would be reused with no cold directory in it.
        """
        prepare_mypy_workspace(prepared, mypy_dir=corpus)
        stamp = json.loads((prepared / ".revision").read_text(encoding="utf-8"))
        del stamp["layout"]
        (prepared / ".revision").write_text(json.dumps(stamp), encoding="utf-8")

        assert prepare_mypy_workspace(prepared, mypy_dir=corpus).reused is False

    def test_missing_stamp_invalidates(self, prepared: Path, corpus: Path) -> None:
        prepare_mypy_workspace(prepared, mypy_dir=corpus)
        (prepared / ".revision").unlink()

        assert prepare_mypy_workspace(prepared, mypy_dir=corpus).reused is False

    def test_truncated_stamp_invalidates(self, prepared: Path, corpus: Path) -> None:
        """An interrupted prepare must rebuild rather than raise."""
        prepare_mypy_workspace(prepared, mypy_dir=corpus)
        (prepared / ".revision").write_text("{not json", encoding="utf-8")

        assert prepare_mypy_workspace(prepared, mypy_dir=corpus).reused is False

    def test_missing_manifest_invalidates(self, prepared: Path, corpus: Path) -> None:
        prepare_mypy_workspace(prepared, mypy_dir=corpus)
        (prepared / "manifest.json").unlink()

        assert prepare_mypy_workspace(prepared, mypy_dir=corpus).reused is False


class TestArtefactLabelling:
    """An artefact has to name its own configuration, not rely on its filename."""

    def test_inference_export_records_the_configuration(self, tmp_path: Path) -> None:
        out = tmp_path / "inference.json"

        export_inference_json(_score(), out, engine="jedi", gate_enabled=False)

        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["engine"] == "jedi"
        assert payload["gate_enabled"] is False

    def test_inference_export_stays_additive(self, tmp_path: Path) -> None:
        """Older artefacts carry neither key, so the generator must keep working without."""
        out = tmp_path / "inference.json"

        export_inference_json(_score(), out)

        payload = json.loads(out.read_text(encoding="utf-8"))
        assert "engine" not in payload
        assert "gate_enabled" not in payload
        assert payload["num_caught_exact"] == 4

    def test_mypy_restore_export_records_the_configuration(self, tmp_path: Path) -> None:
        out = tmp_path / "restore.json"

        export_mypy_json(_mypy_results(), out, engine="jedi", gate_enabled=True)

        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["engine"] == "jedi"
        assert payload["gate_enabled"] is True

    def test_restore_export_records_the_resolution_context(self, tmp_path: Path) -> None:
        """The cold and annotated artefacts are schema-identical apart from this key."""
        out = tmp_path / "restore_cold.json"

        export_mypy_json(
            _mypy_results(),
            out,
            engine="jedi",
            gate_enabled=True,
            resolution_context="cold",
        )

        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["resolution_context"] == "cold"

    def test_mypy_insert_export_records_the_configuration(self, tmp_path: Path) -> None:
        out = tmp_path / "insert.json"

        export_insertion_json(_insertion_results(), out, engine="jedi", gate_enabled=False)

        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["engine"] == "jedi"
        assert payload["gate_enabled"] is False

    @pytest.mark.parametrize(
        "export",
        [
            pytest.param(
                lambda out: export_mypy_json(_mypy_results(), out),
                id="restore",
            ),
            pytest.param(
                lambda out: export_insertion_json(_insertion_results(), out),
                id="insert",
            ),
        ],
    )
    def test_mypy_exports_stay_additive(
        self, tmp_path: Path, export: Callable[[Path], None]
    ) -> None:
        out = tmp_path / "out.json"

        export(out)

        payload = json.loads(out.read_text(encoding="utf-8"))
        assert "engine" not in payload
        assert "gate_enabled" not in payload
        assert "resolution_context" not in payload


def _annotations(result: prepare_mod.MypyPreparationResult) -> list[str]:
    return [target.annotation for file in result.files for target in file.targets]


def _score() -> InferenceScore:
    return InferenceScore(
        tool_name="fangtype-nogate",
        file_count=1,
        num_all=10,
        num_caught_exact=4,
        num_caught_partial=6,
        per_category={},
        sound_count=0,
        complete_count=0,
        out_root=Path("/tmp/out"),
    )


def _empty_group() -> MypyGroupSummary:
    return MypyGroupSummary(
        file_count=0,
        target_count=0,
        matched_targets=0,
        mismatched_targets=0,
        inference_failed_targets=0,
        insertion_failed_targets=0,
    )


def _mypy_results() -> MypyBenchmarkResults:
    return MypyBenchmarkResults(
        mypy_revision="abc123",
        workspace="/tmp/ws",
        manifest_path="/tmp/ws/manifest.json",
        total_python_files=2,
        checkout_total_python_files=2,
        typed_files=_empty_group(),
        untyped_files=_empty_group(),
        file_results=[],
        target_results=[],
    )


def _insertion_results() -> MypyInsertionResults:
    return MypyInsertionResults(
        mypy_revision="abc123",
        workspace="/tmp/ws",
        manifest_path="/tmp/ws/manifest.json",
        eligible_files=0,
        file_results=[],
        target_results=[],
    )
