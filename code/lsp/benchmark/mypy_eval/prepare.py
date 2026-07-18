"""Prepare a reproducible mypy evaluation workspace."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import cast

from benchmark.mypy_eval.normalizer import normalize_annotation
from fangtype.removal import RemovalEngine

_ALWAYS_EXCLUDED_DIRS = frozenset({"__pycache__", ".git"})
_DEFAULT_EXCLUDE_DIRS = frozenset({"test", "test-data"})


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
    manifest_path: str
    total_python_files: int
    typed_file_count: int
    untyped_file_count: int
    error_file_count: int
    files: list[MypyFileManifest]


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
    """Return the default workspace for generated mypy benchmark artifacts."""
    return Path(__file__).resolve().parent.parent / "tmp" / "mypy_eval"


def _iter_python_files(root: Path) -> list[Path]:
    skip = _ALWAYS_EXCLUDED_DIRS | _DEFAULT_EXCLUDE_DIRS
    return sorted(path for path in root.rglob("*.py") if not skip.intersection(path.parts))


def _sha256_text(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _read_git_revision(root: Path) -> str:
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
            head_file = resolved_git_dir / "HEAD"
        else:
            head_file = git_dir / "HEAD"
    else:
        head_file = git_dir / "HEAD"

    if not head_file.exists():
        return "unknown"

    head_content = head_file.read_text(encoding="utf-8").strip()
    if not head_content.startswith("ref:"):
        return head_content

    ref_path = head_content.split(" ", 1)[1]
    ref_file = head_file.parent / ref_path
    if ref_file.exists():
        return ref_file.read_text(encoding="utf-8").strip()
    return "unknown"


def _build_target(entry: dict[str, object]) -> MypyTargetManifest:
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


def prepare_mypy_workspace(workspace: Path | None = None) -> MypyPreparationResult:
    """Create a stripped mypy workspace and manifest for restoration evaluation."""
    mypy_dir = get_mypy_dir()
    workspace = get_default_workspace() if workspace is None else workspace

    original_dir = workspace / "original"
    stripped_dir = workspace / "stripped"
    manifest_path = workspace / "manifest.json"

    shutil.rmtree(workspace, ignore_errors=True)
    original_dir.mkdir(parents=True, exist_ok=True)
    stripped_dir.mkdir(parents=True, exist_ok=True)

    files: list[MypyFileManifest] = []
    typed_file_count = 0
    error_file_count = 0

    for path in _iter_python_files(mypy_dir):
        relative_path = path.relative_to(mypy_dir)
        source = path.read_text(encoding="utf-8")
        original_target = original_dir / relative_path
        stripped_target = stripped_dir / relative_path
        original_target.parent.mkdir(parents=True, exist_ok=True)
        stripped_target.parent.mkdir(parents=True, exist_ok=True)
        original_target.write_text(source, encoding="utf-8")

        try:
            stripped_source, removal_summary = RemovalEngine().remove_types(
                source,
                variables=None,
                include_functions=True,
            )
            targets = [_build_target(entry) for entry in removal_summary["will_remove"]]
            file_manifest = MypyFileManifest(
                relative_path=str(relative_path),
                had_annotations=bool(targets),
                removable_target_count=len(targets),
                original_sha256=_sha256_text(source),
                targets=targets,
            )
        except Exception as exc:
            stripped_source = source
            error_file_count += 1
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
        files.append(file_manifest)

    result = MypyPreparationResult(
        mypy_dir=str(mypy_dir),
        mypy_revision=_read_git_revision(mypy_dir),
        workspace=str(workspace),
        original_dir=str(original_dir),
        stripped_dir=str(stripped_dir),
        manifest_path=str(manifest_path),
        total_python_files=len(files),
        typed_file_count=typed_file_count,
        untyped_file_count=len(files) - typed_file_count - error_file_count,
        error_file_count=error_file_count,
        files=files,
    )

    manifest_path.write_text(json.dumps(asdict(result), indent=2), encoding="utf-8")
    return result
