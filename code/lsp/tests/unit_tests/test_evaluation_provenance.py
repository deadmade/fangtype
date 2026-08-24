"""Tests for the benchmark exporter's provenance stamp.

Three things matter here. ``read_git_revision`` must resolve a commit whether the branch
ref is loose or packed, and must not silently return its ``"unknown"`` fallback for a
repository it can actually read. ``is_working_tree_dirty`` and ``read_fangtype_version``
must read what they claim to read, not a hardcoded stand-in. And ``run_benchmark.py``'s
five ``export_*`` call sites must each forward ``fangtype_revision``/``toolchain``, so
dropping one from a future edit fails a test instead of silently shipping a JSON artefact
with no provenance.
"""

from __future__ import annotations

import importlib.metadata
import platform
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from benchmark import run_benchmark
from benchmark.mypy_eval.prepare import (
    build_toolchain_pins,
    is_working_tree_dirty,
    read_fangtype_version,
    read_git_revision,
)

if TYPE_CHECKING:
    import pytest

_FAKE_SHA = "a" * 40


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(root: Path) -> None:
    _git("init", "-q", cwd=root)
    _git(
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "--allow-empty",
        "-q",
        "-m",
        "init",
        cwd=root,
    )


class TestReadGitRevisionLooseRef:
    """The everyday case: HEAD points at a branch with its own loose ref file."""

    def test_reads_the_loose_ref(self, tmp_path: Path) -> None:
        git_dir = tmp_path / ".git"
        (git_dir / "refs" / "heads").mkdir(parents=True)
        (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        (git_dir / "refs" / "heads" / "main").write_text(f"{_FAKE_SHA}\n", encoding="utf-8")

        assert read_git_revision(tmp_path) == _FAKE_SHA

    def test_detached_head_reads_the_sha_directly(self, tmp_path: Path) -> None:
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "HEAD").write_text(f"{_FAKE_SHA}\n", encoding="utf-8")

        assert read_git_revision(tmp_path) == _FAKE_SHA

    def test_walks_upward_to_find_git_dir(self, tmp_path: Path) -> None:
        """mypy_dir points at the source package, .git sits above it (submodule root)."""
        git_dir = tmp_path / ".git"
        (git_dir / "refs" / "heads").mkdir(parents=True)
        (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        (git_dir / "refs" / "heads" / "main").write_text(f"{_FAKE_SHA}\n", encoding="utf-8")
        nested = tmp_path / "src" / "package"
        nested.mkdir(parents=True)

        assert read_git_revision(nested) == _FAKE_SHA

    def test_submodule_gitdir_file_is_followed(self, tmp_path: Path) -> None:
        """A submodule's .git is a file with `gitdir: <path>`, not a directory."""
        real_git_dir = tmp_path / ".real-git" / "modules" / "sub"
        (real_git_dir / "refs" / "heads").mkdir(parents=True)
        (real_git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        (real_git_dir / "refs" / "heads" / "main").write_text(f"{_FAKE_SHA}\n", encoding="utf-8")

        checkout = tmp_path / "checkout"
        checkout.mkdir()
        (checkout / ".git").write_text(f"gitdir: {real_git_dir}\n", encoding="utf-8")

        assert read_git_revision(checkout) == _FAKE_SHA


class TestReadGitRevisionLinkedWorktree:
    """A linked worktree keeps HEAD private and its refs in the common directory.

    Running a benchmark from a ``git worktree`` is ordinary practice for keeping an
    experiment off the working branch. Resolving the ref against the worktree's own
    directory finds neither a loose ref nor packed-refs there, so every artefact such a
    run exports would carry ``"unknown"`` -- which ``generate_tables.py`` refuses, making
    the whole set unpublishable for a reason that has nothing to do with the measurement.
    """

    def _worktree(self, tmp_path: Path) -> tuple[Path, Path]:
        """Build a common git dir plus a linked worktree pointing at it."""
        common = tmp_path / "main" / ".git"
        (common / "worktrees" / "wt").mkdir(parents=True)
        private = common / "worktrees" / "wt"
        (private / "HEAD").write_text("ref: refs/heads/feature\n", encoding="utf-8")
        (private / "commondir").write_text("../..\n", encoding="utf-8")

        checkout = tmp_path / "wt"
        checkout.mkdir()
        (checkout / ".git").write_text(f"gitdir: {private}\n", encoding="utf-8")
        return checkout, common

    def test_loose_ref_is_read_from_the_common_directory(self, tmp_path: Path) -> None:
        checkout, common = self._worktree(tmp_path)
        (common / "refs" / "heads").mkdir(parents=True)
        (common / "refs" / "heads" / "feature").write_text(f"{_FAKE_SHA}\n", encoding="utf-8")

        assert read_git_revision(checkout) == _FAKE_SHA

    def test_packed_ref_is_read_from_the_common_directory(self, tmp_path: Path) -> None:
        """The state this actually hit -- the branch was packed, so no loose ref existed."""
        checkout, common = self._worktree(tmp_path)
        (common / "packed-refs").write_text(f"{_FAKE_SHA} refs/heads/feature\n", encoding="utf-8")

        assert read_git_revision(checkout) == _FAKE_SHA

    def test_head_is_still_read_from_the_worktree(self, tmp_path: Path) -> None:
        """HEAD is per-worktree; reading the common one would name the wrong branch."""
        checkout, common = self._worktree(tmp_path)
        (common / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        (common / "refs" / "heads").mkdir(parents=True)
        (common / "refs" / "heads" / "main").write_text(f"{'d' * 40}\n", encoding="utf-8")
        (common / "refs" / "heads" / "feature").write_text(f"{_FAKE_SHA}\n", encoding="utf-8")

        assert read_git_revision(checkout) == _FAKE_SHA


class TestReadGitRevisionPackedRefs:
    """A branch git has packed only lives in packed-refs, not in refs/heads/*."""

    def test_reads_a_packed_ref_when_no_loose_ref_exists(self, tmp_path: Path) -> None:
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        # No refs/heads/main file at all -- only packed-refs carries it.
        (git_dir / "packed-refs").write_text(
            "# pack-refs with: peeled fully-peeled sorted\n"
            f"{_FAKE_SHA} refs/heads/main\n"
            f"{'b' * 40} refs/heads/other\n",
            encoding="utf-8",
        )

        assert read_git_revision(tmp_path) == _FAKE_SHA

    def test_loose_ref_wins_over_a_stale_packed_ref(self, tmp_path: Path) -> None:
        git_dir = tmp_path / ".git"
        (git_dir / "refs" / "heads").mkdir(parents=True)
        (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        (git_dir / "refs" / "heads" / "main").write_text(f"{_FAKE_SHA}\n", encoding="utf-8")
        (git_dir / "packed-refs").write_text(f"{'c' * 40} refs/heads/main\n", encoding="utf-8")

        assert read_git_revision(tmp_path) == _FAKE_SHA

    def test_ref_absent_from_both_returns_unknown(self, tmp_path: Path) -> None:
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        (git_dir / "packed-refs").write_text(
            f"{_FAKE_SHA} refs/heads/some-other-branch\n", encoding="utf-8"
        )

        assert read_git_revision(tmp_path) == "unknown"


class TestReadGitRevisionUnresolvable:
    def test_no_git_dir_anywhere_returns_unknown(self, tmp_path: Path) -> None:
        lonely = tmp_path / "not-a-repo"
        lonely.mkdir()

        assert read_git_revision(lonely) == "unknown"

    def test_missing_head_file_returns_unknown(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()

        assert read_git_revision(tmp_path) == "unknown"


class TestIsWorkingTreeDirty:
    """This is what read_git_revision alone cannot show, an uncommitted change on HEAD.

    Scoped to the given root via a pathspec, not the whole repository -- see
    TestIsWorkingTreeDirtyScoping below for the property that actually matters.
    """

    def test_clean_repo_is_not_dirty(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)

        assert is_working_tree_dirty(tmp_path) is False

    def test_modified_tracked_file_is_dirty(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        tracked = tmp_path / "tracked.py"
        tracked.write_text("x = 1\n", encoding="utf-8")
        _git("add", "tracked.py", cwd=tmp_path)
        _git(
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-q",
            "-m",
            "add tracked",
            cwd=tmp_path,
        )

        tracked.write_text("x = 2\n", encoding="utf-8")

        assert is_working_tree_dirty(tmp_path) is True

    def test_untracked_file_alone_is_not_dirty(self, tmp_path: Path) -> None:
        """--untracked-files=no: a new benchmark output file must not flag every run."""
        _init_repo(tmp_path)
        (tmp_path / "untracked.txt").write_text("noise\n", encoding="utf-8")

        assert is_working_tree_dirty(tmp_path) is False

    def test_non_repository_returns_none(self, tmp_path: Path) -> None:
        outside = tmp_path / "no-git-here"
        outside.mkdir()

        assert is_working_tree_dirty(outside) is None

    def test_accepts_a_file_path_and_checks_its_directory(self, tmp_path: Path) -> None:
        """A file argument works too, not only a directory -- subprocess.run needs a cwd."""
        _init_repo(tmp_path)
        a_file = tmp_path / "some_module.py"
        a_file.write_text("pass\n", encoding="utf-8")

        assert is_working_tree_dirty(a_file) is False


class TestIsWorkingTreeDirtyScoping:
    """The property run_benchmark.py actually relies on.

    It passes ``code/lsp``, not the repository root, precisely so that an ordinary
    thesis-authoring edit elsewhere in the checkout does not flip this flag on every
    run. A pathspec that failed to scope correctly would make ``fangtype_dirty`` read
    ``True`` almost always, which carries no information.
    """

    def _repo_with_two_trees(self, tmp_path: Path) -> tuple[Path, Path]:
        _init_repo(tmp_path)
        code_dir = tmp_path / "code"
        thesis_dir = tmp_path / "thesis"
        code_dir.mkdir()
        thesis_dir.mkdir()
        (code_dir / "app.py").write_text("x = 1\n", encoding="utf-8")
        (thesis_dir / "chapter.tex").write_text("\\chapter{X}\n", encoding="utf-8")
        _git("add", "code/app.py", "thesis/chapter.tex", cwd=tmp_path)
        _git(
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-q",
            "-m",
            "add both trees",
            cwd=tmp_path,
        )
        return code_dir, thesis_dir

    def test_a_change_outside_the_scoped_directory_is_not_dirty(self, tmp_path: Path) -> None:
        code_dir, thesis_dir = self._repo_with_two_trees(tmp_path)
        (thesis_dir / "chapter.tex").write_text("\\chapter{Y}\n", encoding="utf-8")

        assert is_working_tree_dirty(code_dir) is False

    def test_a_change_inside_the_scoped_directory_is_dirty(self, tmp_path: Path) -> None:
        code_dir, _thesis_dir = self._repo_with_two_trees(tmp_path)
        (code_dir / "app.py").write_text("x = 2\n", encoding="utf-8")

        assert is_working_tree_dirty(code_dir) is True


class TestReadFangtypeVersion:
    def test_reads_version_from_the_named_package(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "fangtype"\nversion = "9.9.9"\n', encoding="utf-8"
        )

        assert read_fangtype_version(tmp_path) == "9.9.9"

    def test_walks_upward_past_a_differently_named_project(self, tmp_path: Path) -> None:
        """A closer, wrongly-named pyproject.toml must be skipped, not matched by mistake."""
        lsp_dir = tmp_path / "code" / "lsp"
        lsp_dir.mkdir(parents=True)
        (lsp_dir / "pyproject.toml").write_text(
            '[project]\nname = "fangtype"\nversion = "7.7.7"\n', encoding="utf-8"
        )
        src_dir = lsp_dir / "src"
        src_dir.mkdir()
        (src_dir / "pyproject.toml").write_text(
            '[project]\nname = "not-fangtype"\nversion = "0.0.1"\n', encoding="utf-8"
        )
        deeper = src_dir / "fangtype"
        deeper.mkdir()

        assert read_fangtype_version(deeper) == "7.7.7"

    def test_no_matching_pyproject_returns_unknown(self, tmp_path: Path) -> None:
        lonely = tmp_path / "nowhere"
        lonely.mkdir()

        assert read_fangtype_version(lonely) == "unknown"

    def test_finds_the_real_repository_pyproject(self) -> None:
        """The actual entry point run_benchmark.py uses: this repo's own pyproject.toml."""
        here = Path(__file__).resolve()

        assert read_fangtype_version(here) != "unknown"


class TestBuildToolchainPins:
    def test_reports_the_installed_versions(self) -> None:
        pins = build_toolchain_pins()

        assert pins["jedi_version"] == importlib.metadata.version("jedi")
        assert pins["mypy_version"] == importlib.metadata.version("mypy")
        assert pins["python_version"] == platform.python_version()
        assert pins["fangtype_version"] != "unknown"


class TestRunnerExportProvenancePassthrough:
    """Every export_* call site must forward fangtype_revision and toolchain.

    Each test replaces every function _run_*_mode calls before the export with a stub, so
    only the wiring between args and the export call is under test, not the benchmark
    pipeline itself.
    """

    def _base_args(self, tmp_path: Path) -> MagicMock:
        args = MagicMock()
        args.output = tmp_path / "out.json"
        args.engine = "jedi"
        args.no_mypy_gate = False
        args.no_progress = True
        args.workers = 1
        args.benchmark_dir = None
        args.reference = None
        args.force_prepare = False
        args.cold_start = False
        args.fangtype_revision = "deadbeef" * 5
        args.toolchain = {"jedi_version": "0.20.0", "mypy_version": "2.1.0"}
        return args

    def test_inference_mode(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        args = self._base_args(tmp_path)
        export = MagicMock()
        monkeypatch.setattr(
            run_benchmark, "run_inference_benchmark", MagicMock(return_value=MagicMock())
        )
        monkeypatch.setattr(run_benchmark, "summarize_inference", MagicMock(return_value="s"))
        monkeypatch.setattr(run_benchmark, "enumerate_pairs", MagicMock(return_value=[]))
        monkeypatch.setattr(
            run_benchmark, "score_concept_lenient", MagicMock(return_value=MagicMock())
        )
        monkeypatch.setattr(run_benchmark, "export_inference_json", export)

        assert run_benchmark._run_inference_mode(args) == 0

        assert export.call_args.kwargs["fangtype_revision"] == args.fangtype_revision
        assert export.call_args.kwargs["toolchain"] == args.toolchain

    def test_inference_mode_jedi_reference_export_too(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        args = self._base_args(tmp_path)
        args.reference = "jedi"
        export = MagicMock()
        monkeypatch.setattr(
            run_benchmark, "run_inference_benchmark", MagicMock(return_value=MagicMock())
        )
        monkeypatch.setattr(
            run_benchmark, "run_jedi_benchmark", MagicMock(return_value=MagicMock())
        )
        monkeypatch.setattr(run_benchmark, "summarize_inference", MagicMock(return_value="s"))
        monkeypatch.setattr(run_benchmark, "enumerate_pairs", MagicMock(return_value=[]))
        monkeypatch.setattr(
            run_benchmark, "score_concept_lenient", MagicMock(return_value=MagicMock())
        )
        monkeypatch.setattr(run_benchmark, "export_inference_json", export)

        assert run_benchmark._run_inference_mode(args) == 0

        assert export.call_count == 2
        jedi_call = export.call_args_list[1]
        assert jedi_call.kwargs["fangtype_revision"] == args.fangtype_revision
        assert jedi_call.kwargs["toolchain"] == args.toolchain
        # No engine/gate_enabled for the reference runner, on purpose.
        assert "engine" not in jedi_call.kwargs
        assert "gate_enabled" not in jedi_call.kwargs

    def test_insertion_mode(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        args = self._base_args(tmp_path)
        export = MagicMock()
        monkeypatch.setattr(
            run_benchmark, "run_insertion_benchmark", MagicMock(return_value=MagicMock())
        )
        monkeypatch.setattr(run_benchmark, "summarize_inference", MagicMock(return_value="s"))
        monkeypatch.setattr(run_benchmark, "export_inference_json", export)

        assert run_benchmark._run_insertion_mode(args) == 0

        assert export.call_args.kwargs["fangtype_revision"] == args.fangtype_revision
        assert export.call_args.kwargs["toolchain"] == args.toolchain

    def test_mypy_restore_mode(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        args = self._base_args(tmp_path)
        args.mode = "mypy"
        export = MagicMock()
        monkeypatch.setattr(run_benchmark, "get_prepared_dir", MagicMock(return_value=tmp_path))
        monkeypatch.setattr(
            run_benchmark, "prepare_mypy_workspace", MagicMock(return_value=MagicMock())
        )
        monkeypatch.setattr(run_benchmark, "_run_dir", MagicMock(return_value=tmp_path))
        monkeypatch.setattr(
            run_benchmark, "run_mypy_benchmark", MagicMock(return_value=MagicMock())
        )
        monkeypatch.setattr(run_benchmark, "summarize_mypy", MagicMock(return_value="s"))
        monkeypatch.setattr(run_benchmark, "export_mypy_json", export)

        assert run_benchmark._run_mypy_mode(args) == 0

        assert export.call_args.kwargs["fangtype_revision"] == args.fangtype_revision
        assert export.call_args.kwargs["toolchain"] == args.toolchain

    def _drive_restore_mode(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, cold_start: bool
    ) -> tuple[MagicMock, MagicMock]:
        """Run ``_run_mypy_mode`` with everything below the export stubbed out."""
        args = self._base_args(tmp_path)
        args.mode = "mypy"
        args.cold_start = cold_start
        export = MagicMock()
        run = MagicMock(return_value=MagicMock())
        monkeypatch.setattr(run_benchmark, "get_prepared_dir", MagicMock(return_value=tmp_path))
        monkeypatch.setattr(
            run_benchmark, "prepare_mypy_workspace", MagicMock(return_value=MagicMock())
        )
        monkeypatch.setattr(run_benchmark, "_run_dir", MagicMock(return_value=tmp_path))
        monkeypatch.setattr(run_benchmark, "run_mypy_benchmark", run)
        monkeypatch.setattr(run_benchmark, "summarize_mypy", MagicMock(return_value="s"))
        monkeypatch.setattr(run_benchmark, "export_mypy_json", export)

        assert run_benchmark._run_mypy_mode(args) == 0
        return run, export

    def test_restore_mode_labels_the_annotated_arm(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run, export = self._drive_restore_mode(tmp_path, monkeypatch, cold_start=False)

        assert run.call_args.kwargs["cold_start"] is False
        assert export.call_args.kwargs["resolution_context"] == "annotated"

    def test_restore_mode_labels_the_cold_arm(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The two arms are schema-identical, so the label is the only thing telling them apart."""
        run, export = self._drive_restore_mode(tmp_path, monkeypatch, cold_start=True)

        assert run.call_args.kwargs["cold_start"] is True
        assert export.call_args.kwargs["resolution_context"] == "cold"

    def test_mypy_insert_mode(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        args = self._base_args(tmp_path)
        args.mode = "mypy-insert"
        export = MagicMock()
        monkeypatch.setattr(run_benchmark, "get_prepared_dir", MagicMock(return_value=tmp_path))
        monkeypatch.setattr(
            run_benchmark, "prepare_mypy_workspace", MagicMock(return_value=MagicMock())
        )
        monkeypatch.setattr(run_benchmark, "_run_dir", MagicMock(return_value=tmp_path))
        monkeypatch.setattr(
            run_benchmark, "run_mypy_insertion_benchmark", MagicMock(return_value=MagicMock())
        )
        monkeypatch.setattr(run_benchmark, "summarize_insertion", MagicMock(return_value="s"))
        monkeypatch.setattr(run_benchmark, "export_insertion_json", export)

        assert run_benchmark._run_mypy_mode(args) == 0

        assert export.call_args.kwargs["fangtype_revision"] == args.fangtype_revision
        assert export.call_args.kwargs["toolchain"] == args.toolchain
