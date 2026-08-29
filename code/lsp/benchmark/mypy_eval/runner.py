"""Run the mypy restoration benchmark.

Per-file methodology: each evaluated file's stripped text is passed to inference
in memory, while ``path``/``project_root`` point at the original mypy tree — so
cross-module imports resolve against the still-annotated project, and only the
file under test is untyped. Insertions accumulate in memory per file and are
never written back to disk.

``cold_start`` moves ``path``/``project_root`` to the prepared ``coldstart/`` tree,
where every file is stripped. The document under test is byte-identical between the
two arms, because both read their text from ``stripped/``; what changes is the tree a
cross-module name resolves against. That makes the pair a matched comparison over one
variable, and it is the setting a developer adopting the tool on an unannotated project
is actually in.
"""

import json
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path

from benchmark.lsp_client.factory import ClientBridge, map_over_bridge
from benchmark.lsp_client.shim import (
    build_scope_tree,
    is_valid_annotation,
    resolve_inferred_type,
)
from benchmark.mypy_eval.normalizer import normalize_annotation
from benchmark.mypy_eval.prepare import (
    MypyFileManifest,
    MypyPreparationResult,
    MypyTargetManifest,
)

# Per-request LSP timeout. mypy corpus files are large and import-dense, so inference
# can take far longer than the client's 30s default.
_LSP_REQUEST_TIMEOUT = 1200.0


class MypyTargetStatus(Enum):
    """Outcome of one mypy target restoration attempt."""

    MATCH = "match"
    MISMATCH = "mismatch"
    INFERENCE_FAILED = "inference_failed"
    INSERTION_FAILED = "insertion_failed"
    RUN_ERROR = "run_error"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


@dataclass
class MypyTargetResult:
    """Restoration result for one target."""

    relative_path: str
    identifier: str
    target_kind: str
    line_number: int
    expected_annotation: str
    normalized_expected_annotation: str
    inferred_annotation: str | None
    normalized_inferred_annotation: str | None
    status: MypyTargetStatus
    insertion_success: bool
    reason: str | None


@dataclass
class MypyFileResult:
    """Summary for one mypy source file."""

    relative_path: str
    had_annotations: bool
    preparation_error: str | None
    total_targets: int
    matched_targets: int
    mismatched_targets: int
    inference_failed_targets: int
    insertion_failed_targets: int
    run_error: str | None = None


@dataclass
class MypyGroupSummary:
    """Aggregate metrics for typed or untyped files."""

    file_count: int
    target_count: int
    matched_targets: int
    mismatched_targets: int
    inference_failed_targets: int
    insertion_failed_targets: int
    run_error_targets: int = 0
    timeout_targets: int = 0


@dataclass
class MypyBenchmarkResults:
    """Complete mypy benchmark output."""

    mypy_revision: str
    workspace: str
    manifest_path: str
    # Files in the prepared workspace and in the whole checkout before that
    # restriction, carried straight from MypyPreparationResult.
    total_python_files: int
    checkout_total_python_files: int
    typed_files: MypyGroupSummary
    untyped_files: MypyGroupSummary
    file_results: list[MypyFileResult]
    target_results: list[MypyTargetResult]


def _build_target_result(
    relative_path: str,
    target: MypyTargetManifest,
    inferred_annotation: str | None,
    insertion_success: bool,
) -> MypyTargetResult:
    """Classify one target from its inferred type + whether it was inserted."""
    normalized_inferred = (
        normalize_annotation(inferred_annotation) if inferred_annotation is not None else None
    )

    if inferred_annotation is None:
        status = MypyTargetStatus.INFERENCE_FAILED
        reason: str | None = "No type inferred"
    elif not insertion_success:
        status = MypyTargetStatus.INSERTION_FAILED
        reason = "Annotation not inserted"
    elif normalized_inferred == target.normalized_annotation:
        status = MypyTargetStatus.MATCH
        reason = None
    else:
        status = MypyTargetStatus.MISMATCH
        reason = "Semantic mismatch"

    return MypyTargetResult(
        relative_path=relative_path,
        identifier=target.identifier,
        target_kind=target.target_kind,
        line_number=target.line_number,
        expected_annotation=target.annotation,
        normalized_expected_annotation=target.normalized_annotation,
        inferred_annotation=inferred_annotation,
        normalized_inferred_annotation=normalized_inferred,
        status=status,
        insertion_success=insertion_success,
        reason=reason,
    )


def _all_run_error(
    relative_path: str,
    targets: list[MypyTargetManifest],
    error: str,
    status: MypyTargetStatus = MypyTargetStatus.RUN_ERROR,
) -> tuple[MypyFileResult, list[MypyTargetResult]]:
    """Build a whole-file failure result set (a non-timeout RUN_ERROR or a TIMEOUT).

    The file's targets are recorded as failures -- NOT dropped -- so they stay in the
    reported denominator (``len(target_results)``) instead of silently vanishing and
    inflating accuracy. ``status`` distinguishes a timed-out file (``TIMEOUT``) from any
    other processing exception (``RUN_ERROR``).
    """
    label = "timeout" if status is MypyTargetStatus.TIMEOUT else "run error"
    target_results = [
        MypyTargetResult(
            relative_path=relative_path,
            identifier=target.identifier,
            target_kind=target.target_kind,
            line_number=target.line_number,
            expected_annotation=target.annotation,
            normalized_expected_annotation=target.normalized_annotation,
            inferred_annotation=None,
            normalized_inferred_annotation=None,
            status=status,
            insertion_success=False,
            reason=f"{label}: {error}",
        )
        for target in targets
    ]
    file_result = MypyFileResult(
        relative_path=relative_path,
        had_annotations=True,
        preparation_error=None,
        total_targets=len(targets),
        matched_targets=0,
        mismatched_targets=0,
        inference_failed_targets=0,
        insertion_failed_targets=0,
        run_error=error,
    )
    return file_result, target_results


def _load_preparation_result(workspace: Path) -> MypyPreparationResult:
    manifest_path = workspace / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"mypy manifest not found at {manifest_path}\n\n"
            "Run the prepare step before the mypy benchmark."
        )

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = [
        MypyFileManifest(
            relative_path=file_payload["relative_path"],
            had_annotations=file_payload["had_annotations"],
            removable_target_count=file_payload["removable_target_count"],
            original_sha256=file_payload["original_sha256"],
            targets=[
                MypyTargetManifest(
                    identifier=target["identifier"],
                    target_kind=target["target_kind"],
                    line_number=target["line_number"],
                    display_name=target["display_name"],
                    annotation=target["annotation"],
                    normalized_annotation=target["normalized_annotation"],
                    variable_name=target.get("variable_name"),
                    function_name=target.get("function_name"),
                    parameter_name=target.get("parameter_name"),
                )
                for target in file_payload["targets"]
            ],
            preparation_error=file_payload.get("preparation_error"),
        )
        for file_payload in payload["files"]
    ]
    return MypyPreparationResult(
        mypy_dir=payload["mypy_dir"],
        mypy_revision=payload["mypy_revision"],
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
    )


def _build_group_summary(
    files: list[MypyFileResult],
    targets: list[MypyTargetResult],
) -> MypyGroupSummary:
    return MypyGroupSummary(
        file_count=len(files),
        target_count=len(targets),
        matched_targets=sum(1 for target in targets if target.status == MypyTargetStatus.MATCH),
        mismatched_targets=sum(
            1 for target in targets if target.status == MypyTargetStatus.MISMATCH
        ),
        inference_failed_targets=sum(
            1 for target in targets if target.status == MypyTargetStatus.INFERENCE_FAILED
        ),
        insertion_failed_targets=sum(
            1 for target in targets if target.status == MypyTargetStatus.INSERTION_FAILED
        ),
        run_error_targets=sum(
            1 for target in targets if target.status == MypyTargetStatus.RUN_ERROR
        ),
        timeout_targets=sum(1 for target in targets if target.status == MypyTargetStatus.TIMEOUT),
    )


def _load_journal(journal_path: Path) -> dict[str, tuple[MypyFileResult, list[MypyTargetResult]]]:
    """Load completed per-file results from a JSONL journal (empty if absent)."""
    journaled: dict[str, tuple[MypyFileResult, list[MypyTargetResult]]] = {}
    if not journal_path.exists():
        return journaled
    for line in journal_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        file_result = MypyFileResult(**entry["file_result"])
        targets = [
            MypyTargetResult(**{**target, "status": MypyTargetStatus(target["status"])})
            for target in entry["target_results"]
        ]
        journaled[entry["relative_path"]] = (file_result, targets)
    return journaled


def _append_journal(
    journal_path: Path,
    file_result: MypyFileResult,
    target_results: list[MypyTargetResult],
) -> None:
    """Append one completed file's results as a single JSONL line."""
    entry = {
        "relative_path": file_result.relative_path,
        "file_result": asdict(file_result),
        "target_results": [
            {**asdict(target), "status": target.status.value} for target in target_results
        ],
    }
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    with journal_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


def _empty_file_result(file_manifest: MypyFileManifest) -> MypyFileResult:
    """Placeholder result for a non-eligible file (prep error or no annotations)."""
    return MypyFileResult(
        relative_path=file_manifest.relative_path,
        had_annotations=False,
        preparation_error=file_manifest.preparation_error,
        total_targets=0,
        matched_targets=0,
        mismatched_targets=0,
        inference_failed_targets=0,
        insertion_failed_targets=0,
    )


def _evaluate_file(
    bridge: ClientBridge,
    file_manifest: MypyFileManifest,
    stripped_dir: Path,
    uri_base: Path,
) -> tuple[MypyFileResult, list[MypyTargetResult]]:
    """Restore every target in one eligible file via inference; classify each.

    On any exception (e.g. an LSP timeout) the whole file is recorded as RUN_ERROR so its
    targets stay in the denominator rather than silently vanishing.
    """
    try:
        current_source = (stripped_dir / file_manifest.relative_path).read_text(encoding="utf-8")
        uri = (uri_base / file_manifest.relative_path).as_uri()
        hints, name_facts = bridge.collect_sync(uri, current_source, did_open=True)
        tree = build_scope_tree(current_source, hints, name_facts)

        # Per-target classification stays inside the guard: a rare resolve/validate failure records
        # this one file as RUN_ERROR (keeping its targets in the denominator) instead of aborting
        # the whole benchmark run.
        file_target_results = [
            _build_target_result(
                file_manifest.relative_path,
                target,
                inferred := resolve_inferred_type(
                    tree,
                    target.target_kind,
                    target.line_number,
                    target.variable_name,
                    target.function_name,
                    target.parameter_name,
                ),
                is_valid_annotation(inferred),
            )
            for target in file_manifest.targets
        ]

        file_result = MypyFileResult(
            relative_path=file_manifest.relative_path,
            had_annotations=True,
            preparation_error=None,
            total_targets=len(file_target_results),
            matched_targets=sum(
                1 for result in file_target_results if result.status == MypyTargetStatus.MATCH
            ),
            mismatched_targets=sum(
                1 for result in file_target_results if result.status == MypyTargetStatus.MISMATCH
            ),
            inference_failed_targets=sum(
                1
                for result in file_target_results
                if result.status == MypyTargetStatus.INFERENCE_FAILED
            ),
            insertion_failed_targets=sum(
                1
                for result in file_target_results
                if result.status == MypyTargetStatus.INSERTION_FAILED
            ),
        )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        # A per-request LSP timeout surfaces as (asyncio.)TimeoutError; anything else is a
        # genuine processing error. Split them so the report can distinguish "too slow"
        # from "broke".
        status = (
            MypyTargetStatus.TIMEOUT
            if isinstance(exc, TimeoutError)
            else MypyTargetStatus.RUN_ERROR
        )
        label = "timeout" if status is MypyTargetStatus.TIMEOUT else "error"
        print(f"⚠ {file_manifest.relative_path}: {label}: {error}", flush=True)
        return _all_run_error(file_manifest.relative_path, file_manifest.targets, error, status)

    return file_result, file_target_results


def run_mypy_benchmark(
    workspace: Path,
    journal_path: Path | None = None,
    engine: str = "jedi",
    cold_start: bool = False,
) -> MypyBenchmarkResults:
    """Run the mypy restoration benchmark from a prepared workspace."""
    preparation = _load_preparation_result(workspace)
    mypy_dir = Path(preparation.mypy_dir).resolve()
    stripped_dir = Path(preparation.stripped_dir)
    # Where the document under test claims to live, and the import root handed to Jedi.
    # The annotated arm names the real checkout, whose root is the package's parent; the
    # cold arm names the prepared tree, whose root is likewise the package's parent. Both
    # are passed explicitly rather than left to Jedi's walk-up, which would otherwise find
    # code/lsp's pyproject.toml above the prepared workspace and resolve the corpus
    # package through site-packages.
    uri_base = Path(preparation.coldstart_dir) if cold_start else mypy_dir
    project_root = str(uri_base.parent)

    journaled = _load_journal(journal_path) if journal_path is not None else {}
    if journaled:
        print(f"↩ Resuming from journal: {len(journaled)} file(s) already done ({journal_path})")

    eligible_files = [
        manifest
        for manifest in preparation.files
        if manifest.had_annotations and manifest.preparation_error is None
    ]
    total_files = len(eligible_files)
    total_targets = sum(len(manifest.targets) for manifest in eligible_files)

    # Compute per-file results, keyed by relative path, from journal or fresh inference.
    computed: dict[str, tuple[MypyFileResult, list[MypyTargetResult]]] = {}
    pending: list[MypyFileManifest] = []
    done = 0
    done_targets = 0
    matched_so_far = 0
    for file_manifest in eligible_files:
        if file_manifest.relative_path in journaled:
            journaled_result = journaled[file_manifest.relative_path]
            computed[file_manifest.relative_path] = journaled_result
            done += 1
            done_targets += journaled_result[0].total_targets
            matched_so_far += journaled_result[0].matched_targets
            print(
                f"[{done}/{total_files}] {file_manifest.relative_path} "
                f"({len(file_manifest.targets)} targets) ↩ journal",
                flush=True,
            )
        else:
            pending.append(file_manifest)

    def evaluate(
        bridge: ClientBridge, file_manifest: MypyFileManifest, _index: int
    ) -> tuple[MypyFileResult, list[MypyTargetResult]]:
        return _evaluate_file(bridge, file_manifest, stripped_dir, uri_base)

    def report(
        _index: int,
        file_manifest: MypyFileManifest,
        result: tuple[MypyFileResult, list[MypyTargetResult]] | None,
    ) -> None:
        nonlocal done, done_targets, matched_so_far
        if result is None:
            return
        file_result, file_target_results = result
        computed[file_manifest.relative_path] = result
        done += 1
        done_targets += file_result.total_targets
        matched_so_far += file_result.matched_targets
        overall_pct = (matched_so_far / done_targets * 100) if done_targets else 0.0
        print(
            f"[{done}/{total_files}] {file_manifest.relative_path} "
            f"({file_result.total_targets} targets) "
            f"✓ {file_result.matched_targets} matched · "
            f"{done_targets}/{total_targets} targets done · "
            f"{overall_pct:.1f}% matched overall",
            flush=True,
        )
        if journal_path is not None:
            _append_journal(journal_path, file_result, file_target_results)

    map_over_bridge(
        pending,
        make_bridge=lambda: ClientBridge(
            engine=engine, timeout=_LSP_REQUEST_TIMEOUT, project_root=project_root
        ),
        fn=evaluate,
        on_done=report,
    )

    # Reassemble in original manifest order. Resume replays completed files from the
    # journal ahead of the pending ones, so the two lists have to be merged back rather
    # than concatenated.
    file_results: list[MypyFileResult] = []
    target_results: list[MypyTargetResult] = []
    for file_manifest in preparation.files:
        if file_manifest.preparation_error is not None or not file_manifest.had_annotations:
            file_results.append(_empty_file_result(file_manifest))
            continue
        file_result, file_target_results = computed[file_manifest.relative_path]
        file_results.append(file_result)
        target_results.extend(file_target_results)

    typed_files = [result for result in file_results if result.had_annotations]
    untyped_files = [result for result in file_results if not result.had_annotations]
    typed_targets = list(target_results)

    return MypyBenchmarkResults(
        mypy_revision=preparation.mypy_revision,
        workspace=str(workspace),
        manifest_path=preparation.manifest_path,
        total_python_files=preparation.total_python_files,
        checkout_total_python_files=preparation.checkout_total_python_files,
        typed_files=_build_group_summary(typed_files, typed_targets),
        untyped_files=_build_group_summary(untyped_files, []),
        file_results=file_results,
        target_results=target_results,
    )


def as_json(results: MypyBenchmarkResults) -> dict[str, object]:
    """Convert benchmark results to a JSON-serializable payload."""
    payload = asdict(results)
    payload["target_results"] = [
        {
            **target,
            "status": target["status"].value,
        }
        for target in payload["target_results"]
    ]
    return payload
