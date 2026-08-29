"""Prepare a reproducible mypy evaluation workspace."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import shutil
import subprocess
import sys
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import cast

import benchmark.lsp_client.label_parse
import benchmark.mypy_eval.removal_source
import fangtype.removal
import fangtype.server
import fangtype.utils.lsp_request_helper
import fangtype.workflow
from benchmark.lsp_client.factory import ClientBridge
from benchmark.lsp_client.label_parse import as_mapping
from benchmark.mypy_eval.normalizer import normalize_annotation
from benchmark.mypy_eval.removal_source import (
    ClosableRemovalSource,
    LspRemovalSource,
    RemovalSource,
)

_ALWAYS_EXCLUDED_DIRS = frozenset({"__pycache__", ".git"})
_DEFAULT_EXCLUDE_DIRS = frozenset({"test", "test-data"})

# A file the removal source cannot handle is recorded and the loop moves on, because one
# odd corpus file is not a reason to abandon the other 142. A run of them is a different
# fault: the transport is a single server subprocess, so five consecutive failures mean
# that process is gone or answering a shape this cannot read, and every remaining file
# would fail the same way. Five rather than one, because a genuinely file-specific defect
# does not land on five neighbours in a row.
_MAX_CONSECUTIVE_FAILURES = 5

# The stamp is what lets a later run reuse the tree without rebuilding it, so a partly
# failed preparation that stamps itself is served from cache forever. The corpus prepares
# with zero errors today, which makes any error a regression rather than a tolerance to
# budget for. Two percent of the 143-file corpus is 2.86, so it leaves room for two odd
# files while a systemic failure never gets stamped. The manifest is still written and
# returned, so the failure is visible rather than silently retried into the same state.
_MAX_ERROR_FRACTION = 0.02


@dataclass
class MypyTargetManifest:
    """Ground-truth metadata for one removable mypy annotation."""

    identifier: str
    target_kind: str
    line_number: int
    display_name: str
    annotation: str
    normalized_annotation: str
    variable_name: str | None = None
    function_name: str | None = None
    parameter_name: str | None = None


@dataclass
class MypyFileManifest:
    """Prepared file entry in the mypy evaluation manifest."""

    relative_path: str
    had_annotations: bool
    removable_target_count: int
    original_sha256: str
    targets: list[MypyTargetManifest]
    preparation_error: str | None = None


@dataclass
class MypyPreparationResult:
    """Result of preparing a mypy workspace."""

    mypy_dir: str
    mypy_revision: str
    workspace: str
    original_dir: str
    stripped_dir: str
    # Stripped text again, but under the corpus package's own name so the package is
    # importable from the tree's root. ``stripped_dir`` is flat, so nothing there can
    # satisfy ``import mypy.nodes``; see ``prepare_mypy_workspace``.
    coldstart_dir: str
    manifest_path: str
    # Files in the prepared workspace, namely the mypy/ package minus its tests.
    total_python_files: int
    # Files in the whole checkout before that restriction, for comparison.
    checkout_total_python_files: int
    typed_file_count: int
    untyped_file_count: int
    error_file_count: int
    files: list[MypyFileManifest]
    # True when the stripped tree was reused rather than rebuilt. Run-local, so it is
    # dropped before the manifest is written and restored on load.
    reused: bool = False


def get_mypy_dir(mypy_dir: Path | None = None) -> Path:
    """Resolve the mypy source directory (the ``mypy/`` source package)."""
    if mypy_dir is None:
        mypy_dir = Path(__file__).resolve().parent.parent / "data" / "mypy" / "mypy"

    if not mypy_dir.exists():
        raise FileNotFoundError(
            f"mypy benchmark source not found at {mypy_dir}\n\n"
            "Initialize the mypy submodule before running the benchmark:\n"
            "    git submodule update --init code/lsp/benchmark/data/mypy"
        )

    if next(mypy_dir.rglob("*.py"), None) is None:
        raise FileNotFoundError(
            f"mypy benchmark source at {mypy_dir} contains no Python files\n\n"
            "The mypy submodule looks uninitialized (empty checkout). Run:\n"
            "    git submodule update --init code/lsp/benchmark/data/mypy"
        )

    return mypy_dir


def get_default_workspace() -> Path:
    """Return the root for generated mypy benchmark artifacts (holds prepared/ and runs/)."""
    return Path(__file__).resolve().parent.parent / "tmp" / "mypy_eval"


def get_prepared_dir(root: Path | None = None) -> Path:
    """Return the shared stripped-corpus directory, reused across configurations.

    Stripping the corpus is configuration-independent, so every run reads the same
    tree. It lives beside runs/ rather than above it, because preparation rebuilds
    wipe this directory and must not reach the journals.
    """
    return (get_default_workspace() if root is None else root) / "prepared"


def get_run_dir(
    engine: str, *, gate_enabled: bool, cold_start: bool = False, root: Path | None = None
) -> Path:
    """Return the per-configuration run directory, created if absent.

    The mypy gate changes what the server writes, so a gate-on and a gate-off run are
    different measurements and must not share a resume journal. Keying the directory on
    both engine and gate state is what keeps them apart. ``cold_start`` keys it a third
    way for the same reason. The two resolution contexts score the same targets from the
    same stripped text and differ only in the tree their imports resolve against, so a
    shared journal would replay one arm's results under the other's name and the pair
    would agree perfectly by construction.
    """
    gate = "gate-on" if gate_enabled else "gate-off"
    context = "-coldstart" if cold_start else ""
    run_dir = (
        (get_default_workspace() if root is None else root) / "runs" / f"{engine}-{gate}{context}"
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _iter_python_files(root: Path) -> list[Path]:
    skip = _ALWAYS_EXCLUDED_DIRS | _DEFAULT_EXCLUDE_DIRS
    return sorted(path for path in root.rglob("*.py") if not skip.intersection(path.parts))


def _count_checkout_python_files(mypy_dir: Path) -> int:
    """Count every Python file in the whole checkout, not only the prepared workspace.

    ``mypy_dir`` is already restricted to the ``mypy/`` package. The checkout root one
    level up also holds ``mypyc/``, ``misc/``, and the test suites the workspace drops,
    so this count is what the corpus-selection rule actually excludes.
    """
    checkout_root = mypy_dir.parent
    return sum(
        1
        for path in checkout_root.rglob("*.py")
        if not _ALWAYS_EXCLUDED_DIRS.intersection(path.parts)
    )


def _sha256_text(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def read_git_revision(root: Path) -> str:
    """Walk upward from ``root`` to the nearest ``.git`` and read its HEAD commit.

    Public because ``run_benchmark.py`` reuses it to stamp every exported artefact
    with the Fangtype revision that produced it, not just the mypy submodule below.

    Reads HEAD only, so this names the committed revision, not necessarily what was on
    disk when the run happened. A run from a working tree with uncommitted changes
    stamps the same clean SHA a run from a pristine checkout would. Pair this with
    ``is_working_tree_dirty`` when that distinction matters, as ``run_benchmark.py``
    does for every exported artefact.
    """
    # mypy_dir points at the mypy/ source package, but the submodule's .git
    # lives at the checkout root (one level up), so walk upward to find it.
    git_dir = None
    for candidate in (root, *root.parents):
        if (candidate / ".git").exists():
            git_dir = candidate / ".git"
            break
    if git_dir is None:
        return "unknown"

    if git_dir.is_file():
        content = git_dir.read_text(encoding="utf-8").strip()
        if content.startswith("gitdir:"):
            resolved_git_dir = (git_dir.parent / content.split(":", 1)[1].strip()).resolve()
        else:
            resolved_git_dir = git_dir
    else:
        resolved_git_dir = git_dir

    # A linked worktree's private git directory holds HEAD but not the refs. Those live
    # in the common directory, which the private one names in ``commondir``. Resolving a
    # ref against the private directory therefore finds neither a loose ref nor
    # packed-refs, and every artefact a benchmark run from a worktree exports would be
    # stamped "unknown" -- which ``generate_tables.py`` refuses outright.
    common_dir = resolved_git_dir
    commondir_file = resolved_git_dir / "commondir"
    if commondir_file.is_file():
        common_dir = (
            resolved_git_dir / commondir_file.read_text(encoding="utf-8").strip()
        ).resolve()

    head_file = resolved_git_dir / "HEAD"
    if not head_file.exists():
        return "unknown"

    head_content = head_file.read_text(encoding="utf-8").strip()
    if not head_content.startswith("ref:"):
        # Detached HEAD: the file already holds the SHA directly.
        return head_content

    ref_path = head_content.split(" ", 1)[1]
    ref_file = common_dir / ref_path
    if ref_file.exists():
        return ref_file.read_text(encoding="utf-8").strip()

    # No loose ref file. A branch git has packed (e.g. after `git gc` or `git
    # pack-refs`) only lives in packed-refs, so a checkout in that state must not
    # silently fall through to "unknown".
    packed_refs = common_dir / "packed-refs"
    if packed_refs.exists():
        for line in packed_refs.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith(("#", "^")):
                continue
            parts = line.split(" ", 1)
            if len(parts) == 2 and parts[1].strip() == ref_path:
                return parts[0].strip()

    return "unknown"


def read_code_revision(root: Path) -> str:
    """Last commit that touched ``root``, rather than the whole repository's HEAD.

    ``read_git_revision`` answers "what was HEAD", which is the wrong question for an
    artefact that claims to name the code that produced it. This repository holds the
    thesis beside the server, so committing a chapter between two benchmark invocations
    moves HEAD without moving a single line the benchmark executes. The seven artefacts
    then disagree on ``fangtype_revision`` and ``generate_tables.py`` refuses to publish
    them, correctly but for a reason that has nothing to do with the measurement.

    Scoped to ``root`` with a ``--`` pathspec, so only a commit that actually changed the
    measured tree moves the pin. Pair it with ``is_working_tree_dirty`` as before, since
    this still reads committed history and cannot see an uncommitted edit.

    Returns ``"unknown"`` rather than guessing when the check cannot be made, matching
    ``read_git_revision``'s sentinel so ``_pin`` refuses it downstream either way.
    """
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%H", "--", "."],
            cwd=root if root.is_dir() else root.parent,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    revision = result.stdout.strip()
    return revision if result.returncode == 0 and revision else "unknown"


def is_working_tree_dirty(root: Path) -> bool | None:
    """Whether ``root`` itself, and everything under it, has uncommitted changes.

    ``read_git_revision`` reads committed HEAD only, so it cannot see this by itself.
    Scoped to ``root`` via a ``--`` pathspec, not the whole repository, on purpose. A
    plain ``git status`` reports on the entire checkout, and during ordinary thesis
    authoring ``thesis/`` almost always has uncommitted edits that cannot move an
    inference or insertion result, so an unscoped check would read ``True`` on
    essentially every run and carry no information. ``run_benchmark.py`` passes
    ``code/lsp``, the tree whose state can actually change what a run produces.

    Nothing in this benchmark suite currently reads the resulting flag back. It is
    recorded on the exported artefact for a human auditing provenance later, not
    enforced here. ``generate_tables.py`` in particular must keep running on a dirty
    tree, since blocking regeneration would get in the way of ordinary development.

    Returns ``None``, rather than guessing, when the check could not be made, for
    instance because ``git`` is not on ``PATH`` or ``root`` is not inside a work tree.
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no", "--", "."],
            cwd=root if root.is_dir() else root.parent,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return bool(result.stdout.strip())


def read_fangtype_version(root: Path) -> str:
    """Walk upward from ``root`` to the fangtype package's ``pyproject.toml`` and read
    ``project.version``.

    This is the documented source for the Fangtype version pin the thesis cites, which
    ``thesis/evaluation/generate_tables.py`` reads back out of the artefacts into
    ``generated/versions.json``. Read directly rather than through ``importlib.metadata``
    because the
    devshell puts ``code/lsp/src`` on ``PYTHONPATH`` rather than installing the package,
    so it carries no distribution metadata for ``importlib.metadata`` to find.
    """
    for candidate in (root, *root.parents):
        pyproject = candidate / "pyproject.toml"
        if not pyproject.exists():
            continue
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError:
            continue
        project = data.get("project", {})
        if project.get("name") == "fangtype":
            return str(project.get("version", "unknown"))
    return "unknown"


def build_toolchain_pins() -> dict[str, str]:
    """Snapshot the Fangtype/Jedi/mypy/CPython versions the running interpreter has
    installed.

    Stamped onto every exported artefact alongside ``fangtype_revision``, so the pins the
    thesis cites are derived from the artefacts rather than taken on the operator's word.
    """
    return {
        "fangtype_version": read_fangtype_version(Path(__file__)),
        "jedi_version": importlib.metadata.version("jedi"),
        "mypy_version": importlib.metadata.version("mypy"),
        "python_version": platform.python_version(),
    }


def _removal_path_fingerprint() -> str:
    """Hash every file whose contents can change what stripping produces, so a change
    anywhere on that path invalidates the cache.

    Hashing ``fangtype/removal/`` alone was sufficient while preparation called
    ``RemovalEngine`` in-process. Stripping now leaves that package the way the VS Code
    client leaves it, over the same wire protocol, so the package's own hash can no
    longer see a change made anywhere else on that path. The corpus revision cannot see
    it either, since none of these files live in the submodule. Six things are hashed
    for that reason, and a change to any one of them can change the stripped bytes while
    the corpus revision and the removal package's own hash both sit still.
    """
    removal_package_root = Path(str(fangtype.removal.__file__)).resolve().parent
    entries: list[tuple[str, Path]] = [
        (f"fangtype/removal/{path.relative_to(removal_package_root).as_posix()}", path)
        # The engine itself. It decides which annotations become removal targets.
        for path in removal_package_root.rglob("*.py")
    ]
    entries.extend(
        [
            # remove_types and preview_removals sit between the handler and the engine.
            ("fangtype/workflow.py", Path(str(fangtype.workflow.__file__)).resolve()),
            # The two removal handlers reshape the request into the wire response.
            ("fangtype/server.py", Path(str(fangtype.server.__file__)).resolve()),
            # build_full_document_workspace_edit is now how the stripped text travels.
            (
                "fangtype/utils/lsp_request_helper.py",
                Path(str(fangtype.utils.lsp_request_helper.__file__)).resolve(),
            ),
            # modified_source_from_edit decides the stripped bytes on arrival.
            (
                "benchmark/lsp_client/label_parse.py",
                Path(str(benchmark.lsp_client.label_parse.__file__)).resolve(),
            ),
            # Drives both requests and reads the result back into a manifest entry.
            (
                "benchmark/mypy_eval/removal_source.py",
                Path(str(benchmark.mypy_eval.removal_source.__file__)).resolve(),
            ),
        ]
    )
    digest = hashlib.sha256()
    for label, path in sorted(entries, key=lambda entry: entry[0]):
        digest.update(label.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


# Bumped whenever the prepared workspace grows or loses a directory. The stripping is
# unchanged by such a move, so ``_removal_path_fingerprint`` cannot see it, and a tree
# prepared before ``coldstart/`` existed would otherwise be reused without it.
_WORKSPACE_LAYOUT = 2


def _stamp_path(workspace: Path) -> Path:
    return workspace / ".revision"


def _current_stamp(mypy_dir: Path, file_count: int, transport: str) -> dict[str, object]:
    """The reuse key for a prepared tree, including the route its stripping took.

    ``transport`` is the removal source's own label rather than a constant, which is the
    whole point of the field. Preparation used to call RemovalEngine in-process, and a tree
    built that way is missing the transport-layer bugs LspRemovalSource is meant to surface,
    so it must rebuild rather than be served as if it were produced the current way. Stamped
    unconditionally as ``"lsp"``, the field said that of an in-process tree too, which is
    the one thing it exists to prevent.
    """
    return {
        "mypy_dir": str(mypy_dir),
        "mypy_revision": read_git_revision(mypy_dir),
        "stripping_fingerprint": _removal_path_fingerprint(),
        "file_count": file_count,
        "layout": _WORKSPACE_LAYOUT,
        "prepare_transport": transport,
    }


def _may_stamp(error_file_count: int, total_file_count: int) -> bool:
    """Whether a preparation that hit ``error_file_count`` failures may cache itself.

    The stamp is a promise that the tree beside it is the ground truth every later run
    may reuse without rebuilding. A preparation that failed on part of the corpus wrote a
    stripped file that is really the unstripped source, with an empty target list beside
    it, and stamping that hands the same hole to every run afterwards until someone passes
    ``force``. Refusing the stamp costs one rebuild and makes the failure recur visibly
    instead of hardening into the cache.
    """
    return error_file_count <= _MAX_ERROR_FRACTION * total_file_count


def _load_cached_preparation(workspace: Path, stamp: dict[str, object]) -> MypyPreparationResult:
    """Rebuild the preparation result from a manifest whose stamp already matched."""
    payload = json.loads((workspace / "manifest.json").read_text(encoding="utf-8"))
    files = [
        MypyFileManifest(
            relative_path=entry["relative_path"],
            had_annotations=entry["had_annotations"],
            removable_target_count=entry["removable_target_count"],
            original_sha256=entry["original_sha256"],
            targets=[MypyTargetManifest(**target) for target in entry["targets"]],
            preparation_error=entry.get("preparation_error"),
        )
        for entry in payload["files"]
    ]
    return MypyPreparationResult(
        mypy_dir=payload["mypy_dir"],
        mypy_revision=str(stamp["mypy_revision"]),
        workspace=payload["workspace"],
        original_dir=payload["original_dir"],
        stripped_dir=payload["stripped_dir"],
        coldstart_dir=payload["coldstart_dir"],
        manifest_path=payload["manifest_path"],
        total_python_files=payload["total_python_files"],
        checkout_total_python_files=payload["checkout_total_python_files"],
        typed_file_count=payload["typed_file_count"],
        untyped_file_count=payload["untyped_file_count"],
        error_file_count=payload["error_file_count"],
        files=files,
        reused=True,
    )


def _reusable_preparation(
    workspace: Path, stamp: dict[str, object]
) -> MypyPreparationResult | None:
    """Return the cached preparation when the stamp and manifest are both intact."""
    stamp_file = _stamp_path(workspace)
    if not stamp_file.exists() or not (workspace / "manifest.json").exists():
        return None
    try:
        if json.loads(stamp_file.read_text(encoding="utf-8")) != stamp:
            return None
        return _load_cached_preparation(workspace, stamp)
    except (OSError, ValueError, KeyError, TypeError):
        # A truncated stamp or manifest from an interrupted prepare is not an error,
        # it just means the tree has to be rebuilt.
        return None


def _build_target(entry: object) -> MypyTargetManifest:
    """Build one manifest entry from a removal record.

    ``entry`` is a ``RemovalRecord`` (``removal/engine.py``), but over LSP it arrives as
    the pygls namedtuple ``_dict_to_object`` produces rather than a ``dict`` (see
    ``as_mapping``'s docstring). Normalise first so every ``entry[...]``/``entry.get(...)``
    read below works the same for both shapes.
    """
    entry = as_mapping(entry)
    annotation = str(entry["type"])
    return MypyTargetManifest(
        identifier=str(entry["variable"]),
        target_kind=str(entry.get("target_kind") or "variable"),
        line_number=int(cast("int | str", entry["line"])),  # JSON line number
        display_name=str(entry["variable"]),
        annotation=annotation,
        normalized_annotation=normalize_annotation(annotation),
        variable_name=(
            str(entry["variable"])
            if str(entry.get("target_kind") or "variable") in {"variable", "attribute"}
            else None
        ),
        function_name=(
            str(entry["function_name"]) if entry.get("function_name") is not None else None
        ),
        parameter_name=(
            str(entry["parameter_name"]) if entry.get("parameter_name") is not None else None
        ),
    )


def _strip_corpus(
    removal_source: RemovalSource,
    source_files: list[Path],
    *,
    mypy_dir: Path,
    original_dir: Path,
    stripped_dir: Path,
    coldstart_dir: Path,
) -> tuple[list[MypyFileManifest], int, int]:
    """Write the original, stripped and cold-start copy of every corpus file.

    A file that fails to strip is not fatal on its own. It is recorded with its own
    ``preparation_error``, its stripped copy is the unmodified source, and the loop
    carries on, because one unparseable file should not cost the other 142. A run of
    consecutive failures is fatal, since the removal source is one server subprocess and a
    dead or misspeaking one fails every remaining file identically -- continuing would
    spend the whole corpus producing an empty manifest.
    """
    files: list[MypyFileManifest] = []
    typed_file_count = 0
    error_file_count = 0
    consecutive_failures = 0

    for path in source_files:
        relative_path = path.relative_to(mypy_dir)
        source = path.read_text(encoding="utf-8")
        original_target = original_dir / relative_path
        stripped_target = stripped_dir / relative_path
        coldstart_target = coldstart_dir / relative_path
        original_target.parent.mkdir(parents=True, exist_ok=True)
        stripped_target.parent.mkdir(parents=True, exist_ok=True)
        coldstart_target.parent.mkdir(parents=True, exist_ok=True)
        original_target.write_text(source, encoding="utf-8")

        try:
            # The URI names the corpus file, whose bytes on disk are exactly ``source``,
            # so an LSP source can read it without the harness opening the document.
            stripped_source, removal_records = removal_source.strip(path.as_uri(), source)
            targets = [_build_target(entry) for entry in removal_records]
            file_manifest = MypyFileManifest(
                relative_path=str(relative_path),
                had_annotations=bool(targets),
                removable_target_count=len(targets),
                original_sha256=_sha256_text(source),
                targets=targets,
            )
            consecutive_failures = 0
        except Exception as exc:
            stripped_source = source
            error_file_count += 1
            consecutive_failures += 1
            file_manifest = MypyFileManifest(
                relative_path=str(relative_path),
                had_annotations=False,
                removable_target_count=0,
                original_sha256=_sha256_text(source),
                targets=[],
                preparation_error=str(exc),
            )

        if file_manifest.had_annotations:
            typed_file_count += 1

        stripped_target.write_text(stripped_source, encoding="utf-8")
        coldstart_target.write_text(stripped_source, encoding="utf-8")
        files.append(file_manifest)

        if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
            raise RuntimeError(
                f"prepare: {consecutive_failures} consecutive files failed to strip, "
                f"the last being {relative_path}; the removal source is not answering, "
                "so the remaining files would fail the same way"
            )

    return files, typed_file_count, error_file_count


def default_removal_source() -> RemovalSource:
    """Build the removal source a real preparation run uses, and the server behind it.

    Separated from ``prepare_mypy_workspace`` so a test can swap the transport for the
    in-process engine with a single monkeypatch, rather than by threading an argument
    through twenty-six call sites that are about caching and manifest shape and have no
    opinion about how the stripping reaches the engine.

    ``mypy_enabled=False`` is passed per client rather than through ``set_mypy_gate``,
    whose mutation is module-level and would still be in force when the evaluation bridge
    is built later in the same process, silently turning the measured gate off. Removal
    is a LibCST pass that never consults the validator, so switching it off here cannot
    move a stripped byte, and it makes a stray ``didOpen`` cost a scheduling round rather
    than a full mypy run.
    """
    return LspRemovalSource(ClientBridge(config_overrides={"mypy_enabled": False}))


def prepare_mypy_workspace(
    workspace: Path | None = None,
    *,
    mypy_dir: Path | None = None,
    force: bool = False,
    removal: RemovalSource | None = None,
) -> MypyPreparationResult:
    """Create a stripped mypy workspace and manifest, reusing an intact one.

    Stripping the corpus is the same work for every configuration and takes far longer
    than it takes to check whether the last one still applies, so a run whose stamp
    matches reads the existing tree instead of rebuilding it. ``force`` rebuilds
    unconditionally.

    ``removal`` names how a file's annotations come off. ``None`` asks
    ``default_removal_source`` for the LSP route, which is the one the extension takes,
    and that source is built only once the cache has been ruled out so a reused tree
    starts no server. A caller that supplies its own source keeps ownership of it and is
    responsible for closing it.
    """
    mypy_dir = get_mypy_dir(mypy_dir)
    workspace = get_prepared_dir() if workspace is None else workspace

    original_dir = workspace / "original"
    stripped_dir = workspace / "stripped"
    # The corpus package's own name (``mypy``), so the cold tree root is an import root.
    coldstart_dir = workspace / "coldstart" / mypy_dir.name
    manifest_path = workspace / "manifest.json"

    source_files = _iter_python_files(mypy_dir)
    # Read off the class rather than off an instance, because the source is built only once
    # reuse has been ruled out, so that a reused tree never pays for a server subprocess and
    # the cache lookup needs a transport before then. ``removal is None`` is the route
    # ``default_removal_source`` takes, which is ``LspRemovalSource``'s. One route past this
    # remains, namely replacing ``default_removal_source`` itself, which the unit tests do;
    # each of those writes into a ``tmp_path`` of its own, so none can reach the shared tree
    # under ``benchmark/tmp`` that the stamp is there to protect.
    transport = LspRemovalSource.transport if removal is None else removal.transport
    stamp = _current_stamp(mypy_dir, len(source_files), transport)
    if not force:
        cached = _reusable_preparation(workspace, stamp)
        if cached is not None:
            return cached

    shutil.rmtree(workspace, ignore_errors=True)
    original_dir.mkdir(parents=True, exist_ok=True)
    stripped_dir.mkdir(parents=True, exist_ok=True)
    coldstart_dir.mkdir(parents=True, exist_ok=True)

    # Resolved after the cache check, so a reused tree never pays for a server subprocess.
    owns_removal = removal is None
    removal_source = default_removal_source() if removal is None else removal
    try:
        files, typed_file_count, error_file_count = _strip_corpus(
            removal_source,
            source_files,
            mypy_dir=mypy_dir,
            original_dir=original_dir,
            stripped_dir=stripped_dir,
            coldstart_dir=coldstart_dir,
        )
    finally:
        # Only a source this function built is this function's to shut down.
        if owns_removal and isinstance(removal_source, ClosableRemovalSource):
            removal_source.close()

    result = MypyPreparationResult(
        mypy_dir=str(mypy_dir),
        mypy_revision=str(stamp["mypy_revision"]),
        workspace=str(workspace),
        original_dir=str(original_dir),
        stripped_dir=str(stripped_dir),
        coldstart_dir=str(coldstart_dir),
        manifest_path=str(manifest_path),
        total_python_files=len(files),
        checkout_total_python_files=_count_checkout_python_files(mypy_dir),
        typed_file_count=typed_file_count,
        untyped_file_count=len(files) - typed_file_count - error_file_count,
        error_file_count=error_file_count,
        files=files,
    )

    payload = asdict(result)
    del payload["reused"]
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    # Written last, so an interrupted prepare leaves no stamp and the next run rebuilds.
    if _may_stamp(error_file_count, len(files)):
        _stamp_path(workspace).write_text(json.dumps(stamp, indent=2), encoding="utf-8")
    else:
        print(
            f"prepare: {error_file_count} of {len(files)} files failed to strip; "
            "refusing to stamp the tree, so the next run rebuilds rather than reusing it",
            file=sys.stderr,
        )
    return result
