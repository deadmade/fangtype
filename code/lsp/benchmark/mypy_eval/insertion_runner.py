"""Run the mypy **insertion** benchmark."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from benchmark.lsp_client.factory import ClientBridge, map_over_bridge
from benchmark.mypy_eval.normalizer import normalize_annotation
from benchmark.mypy_eval.runner import _load_preparation_result
from benchmark.typeevalpy import official
from benchmark.typeevalpy.fact_emitter import emit_facts
from benchmark.typeevalpy.insertion_runner import (
    FactKey,
    _compiles,
    _fact_key,
    classify_file,
    inserted_types,
)

# The three TypeEvalPy fact buckets, in report order. Shared denominator taxonomy for
# the inference -> insertion funnel (mirrors benchmark.typeevalpy.insertion_runner).
_FACT_CATEGORIES: tuple[str, ...] = ("function_returns", "function_parameters", "local_variables")


def _category_counts(facts: list[dict]) -> dict[str, int]:
    """Bucket emitted facts into the three fact categories and count each."""
    bucketed = official.categorize_facts(facts)
    return {category: len(bucketed[category]) for category in _FACT_CATEGORIES}


def _distinct_name_counts(facts: list[dict]) -> dict[str, int]:
    """Category counts after collapsing facts that share a ``_fact_key`` (drops line).

    The per-binding funnel emits one fact per assignment site, so a reassigned variable
    (``x = 1; x = "a"``) contributes several ``local_variables`` facts under one
    ``(scope, name, kind)`` key that a single legal annotation can never all satisfy.
    Deduping by ``_fact_key`` yields the *distinct-name* denominator: one entry per name.

    Applied to ``classify_file``'s ``matched`` list this also gives the honest
    distinct-*correct* count — a name is kept iff at least one of its bindings matched
    the inserted type, since ``matched`` holds exactly those facts.
    """
    seen: dict[FactKey, dict] = {}
    for fact in facts:
        seen.setdefault(_fact_key(fact), fact)
    return _category_counts(list(seen.values()))


if TYPE_CHECKING:
    from collections.abc import Callable

    from benchmark.mypy_eval.prepare import MypyFileManifest, MypyTargetManifest

# Per-request LSP timeout. mypy corpus files are large and import-dense, so inference
# can take far longer than the client's 30s default. Mirrors runner.py.
_LSP_REQUEST_TIMEOUT = 1200.0


class MypyInsertionTargetStatus(Enum):
    """Outcome of one mypy target insertion attempt."""

    INSERTED_CORRECT = "inserted_correct"
    INSERTED_WRONG = "inserted_wrong"
    NOT_INSERTED = "not_inserted"


class MypyInsertionFileStatus(Enum):
    """Outcome of one mypy file's insertion run."""

    OK = "ok"  # inserted + parsed
    INSERTION_FAILED = "insertion_failed"  # server produced no edit (modified is None)
    PARSE_FAILED = "parse_failed"  # modified source does not compile
    RUN_ERROR = "run_error"  # exception while processing the file


@dataclass
class MypyInsertionTargetResult:
    """Insertion result for one target."""

    relative_path: str
    identifier: str
    target_kind: str
    line_number: int
    expected_annotation: str
    normalized_expected_annotation: str
    inserted_annotation: str | None
    normalized_inserted_annotation: str | None
    status: MypyInsertionTargetStatus


@dataclass
class MypyInsertionFileResult:
    """Summary for one mypy source file's insertion run."""

    relative_path: str
    status: MypyInsertionFileStatus
    total_targets: int
    inserted_correct: int
    inserted_wrong: int
    not_inserted: int
    parsed: bool
    run_error: str | None = None
    # Inference -> insertion funnel, per fact category. ``inferred`` is the type set the
    # server would annotate (the fidelity denominator); ``inserted`` is what actually
    # landed in the file (any type); ``correct`` is what landed carrying the *inferred*
    # type intact. Default empty so older journals (without these keys) still load.
    inferred_by_category: dict[str, int] = field(default_factory=dict)
    inserted_by_category: dict[str, int] = field(default_factory=dict)
    correct_by_category: dict[str, int] = field(default_factory=dict)
    # Distinct-name funnel: the same three counts after collapsing per-binding duplicates
    # by (scope, name, kind) (``_distinct_name_counts``). This is the honest denominator
    # for reassigned variables — a single legal annotation can't satisfy several
    # flow-sensitive types under one name. Default empty so older journals still load.
    inferred_distinct_by_category: dict[str, int] = field(default_factory=dict)
    inserted_distinct_by_category: dict[str, int] = field(default_factory=dict)
    correct_distinct_by_category: dict[str, int] = field(default_factory=dict)
    # Insert-path miss attribution from the server: {reason: count} over surfaced variable
    # NAMES (``selected`` / ``all_mypy_invalid``). Diagnostic only; empty for older
    # journals and whenever the server reports nothing. See TypeAnnotationWorkflow
    # .variable_drop_reasons for the (deliberately partial) reason taxonomy.
    variable_drop_reasons: dict[str, int] = field(default_factory=dict)


@dataclass
class MypyInsertionResults:
    """Complete mypy insertion benchmark output."""

    mypy_revision: str
    workspace: str
    manifest_path: str
    eligible_files: int
    file_results: list[MypyInsertionFileResult]
    target_results: list[MypyInsertionTargetResult]


def _bare_indices(
    modified_source: str,
) -> tuple[
    dict[tuple[str | None, str], str],
    dict[str | None, str],
    dict[str, str],
    dict[str, str],
]:
    """Reduce ``inserted_types()`` to bare-name lookup indices for manifest matching."""
    inserted = inserted_types(modified_source)
    params: dict[tuple[str | None, str], str] = {}
    returns: dict[str | None, str] = {}
    variables: dict[str, str] = {}
    attributes: dict[str, str] = {}
    for (scope, name, kind), ann in inserted.items():
        bare_func = scope.split(".")[-1] if scope else None
        if kind == "return":
            returns[bare_func] = ann
            continue
        if name is None:
            continue
        if kind == "param":
            params[(bare_func, name)] = ann
        elif kind == "variable":
            variables[name] = ann
        elif kind == "attribute":
            attributes[name] = ann  # name is "self.x"
    return params, returns, variables, attributes


def _lookup_inserted_annotation(
    target: MypyTargetManifest,
    params: dict[tuple[str | None, str], str],
    returns: dict[str | None, str],
    variables: dict[str, str],
    attributes: dict[str, str],
) -> str | None:
    """Look up what (if anything) was inserted for ``target`` by its ``target_kind``."""
    if target.target_kind == "function_param":
        if target.parameter_name is None:
            return None
        return params.get((target.function_name, target.parameter_name))
    if target.target_kind == "function_return":
        return returns.get(target.function_name)
    if target.target_kind == "variable":
        if target.variable_name is None:
            return None
        return variables.get(target.variable_name)
    if target.target_kind == "attribute":
        if target.variable_name is None:
            return None
        return attributes.get(target.variable_name)
    return None


def _classify_target(
    relative_path: str,
    target: MypyTargetManifest,
    params: dict[tuple[str | None, str], str],
    returns: dict[str | None, str],
    variables: dict[str, str],
    attributes: dict[str, str],
) -> MypyInsertionTargetResult:
    """Classify one target from what (if anything) was inserted for it."""
    inserted = _lookup_inserted_annotation(target, params, returns, variables, attributes)
    normalized_inserted = normalize_annotation(inserted) if inserted is not None else None

    if inserted is None:
        status = MypyInsertionTargetStatus.NOT_INSERTED
    elif normalized_inserted == target.normalized_annotation:
        status = MypyInsertionTargetStatus.INSERTED_CORRECT
    else:
        status = MypyInsertionTargetStatus.INSERTED_WRONG

    return MypyInsertionTargetResult(
        relative_path=relative_path,
        identifier=target.identifier,
        target_kind=target.target_kind,
        line_number=target.line_number,
        expected_annotation=target.annotation,
        normalized_expected_annotation=target.normalized_annotation,
        inserted_annotation=inserted,
        normalized_inserted_annotation=normalized_inserted,
        status=status,
    )


def _all_not_inserted(
    relative_path: str,
    status: MypyInsertionFileStatus,
    targets: list[MypyTargetManifest],
    run_error: str | None = None,
    inferred: dict[str, int] | None = None,
    inferred_distinct: dict[str, int] | None = None,
    variable_drop_reasons: dict[str, int] | None = None,
) -> tuple[MypyInsertionFileResult, list[MypyInsertionTargetResult]]:
    """Build a whole-file NOT_INSERTED result set (insertion, parse, or run failure).

    ``inferred``/``inferred_distinct`` carry the per-category inferred-fact counts
    (per-binding and distinct-name) when known (insertion/parse failure — inference ran,
    but nothing usable landed); both stay empty for a run error, where inference may not
    have completed. ``inserted``/``correct`` are always empty here — nothing landed.
    """
    target_results = [
        MypyInsertionTargetResult(
            relative_path=relative_path,
            identifier=target.identifier,
            target_kind=target.target_kind,
            line_number=target.line_number,
            expected_annotation=target.annotation,
            normalized_expected_annotation=target.normalized_annotation,
            inserted_annotation=None,
            normalized_inserted_annotation=None,
            status=MypyInsertionTargetStatus.NOT_INSERTED,
        )
        for target in targets
    ]
    file_result = MypyInsertionFileResult(
        relative_path=relative_path,
        status=status,
        total_targets=len(targets),
        inserted_correct=0,
        inserted_wrong=0,
        not_inserted=len(targets),
        parsed=False,
        run_error=run_error,
        inferred_by_category=inferred or {},
        inferred_distinct_by_category=inferred_distinct or {},
        variable_drop_reasons=variable_drop_reasons or {},
    )
    return file_result, target_results


def _load_journal(
    journal_path: Path,
) -> dict[str, tuple[MypyInsertionFileResult, list[MypyInsertionTargetResult]]]:
    """Load completed per-file results from a JSONL journal (empty if absent)."""
    journaled: dict[str, tuple[MypyInsertionFileResult, list[MypyInsertionTargetResult]]] = {}
    if not journal_path.exists():
        return journaled
    for line in journal_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        file_payload = entry["file_result"]
        file_result = MypyInsertionFileResult(
            **{**file_payload, "status": MypyInsertionFileStatus(file_payload["status"])}
        )
        targets = [
            MypyInsertionTargetResult(
                **{**target, "status": MypyInsertionTargetStatus(target["status"])}
            )
            for target in entry["target_results"]
        ]
        journaled[entry["relative_path"]] = (file_result, targets)
    return journaled


def _append_journal(
    journal_path: Path,
    file_result: MypyInsertionFileResult,
    target_results: list[MypyInsertionTargetResult],
) -> None:
    """Append one completed file's results as a single JSONL line."""
    entry = {
        "relative_path": file_result.relative_path,
        "file_result": {**asdict(file_result), "status": file_result.status.value},
        "target_results": [
            {**asdict(target), "status": target.status.value} for target in target_results
        ],
    }
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    with journal_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


def _insert_file(
    bridge: ClientBridge,
    file_manifest: MypyFileManifest,
    original_dir: Path,
    stripped_dir: Path,
) -> tuple[MypyInsertionFileResult, list[MypyInsertionTargetResult]]:
    """Drive the server's real insert over one file and classify each target.

    On any exception the whole file is recorded as RUN_ERROR (targets NOT_INSERTED) so its
    targets stay in the reported denominator rather than silently vanishing.
    """
    rel = file_manifest.relative_path
    try:
        stripped_source = (stripped_dir / rel).read_text(encoding="utf-8")
        uri = (original_dir / rel).as_uri()

        # Inferred facts — the fidelity denominator: every type the server would annotate
        # on this file. did_open=True syncs the STRIPPED text (the on-disk file at ``uri``
        # is still the annotated original), matching the insert call below and the
        # restoration path. This is a second inference pass; the server's DocumentCache
        # absorbs most of the cost when the (uri, version) matches the insert call.
        hints, name_facts = bridge.collect_sync(uri, stripped_source, did_open=True)
        candidates = emit_facts(stripped_source, hints, name_facts, filename=Path(rel).name)
        inferred_counts = _category_counts(candidates)
        inferred_distinct_counts = _distinct_name_counts(candidates)

        _success, modified, drop_reasons = bridge.insert_sync(uri, stripped_source)

        if modified is None:
            return _all_not_inserted(
                rel,
                MypyInsertionFileStatus.INSERTION_FAILED,
                file_manifest.targets,
                inferred=inferred_counts,
                inferred_distinct=inferred_distinct_counts,
                variable_drop_reasons=drop_reasons,
            )

        if not _compiles(modified):
            return _all_not_inserted(
                rel,
                MypyInsertionFileStatus.PARSE_FAILED,
                file_manifest.targets,
                inferred=inferred_counts,
                inferred_distinct=inferred_distinct_counts,
                variable_drop_reasons=drop_reasons,
            )

        # Fidelity classification (vs the inferred type, not ground truth):
        # ``matched`` = inserted AND the inserted annotation equals the inferred type;
        # ``inserted`` = annotated with any type. Mirrors the TypeEvalPy insertion runner.
        matched, inserted = classify_file(candidates, modified)

        params, returns, variables, attributes = _bare_indices(modified)
        file_target_results = [
            _classify_target(rel, target, params, returns, variables, attributes)
            for target in file_manifest.targets
        ]
        file_result = MypyInsertionFileResult(
            relative_path=rel,
            status=MypyInsertionFileStatus.OK,
            total_targets=len(file_manifest.targets),
            inserted_correct=sum(
                1
                for result in file_target_results
                if result.status == MypyInsertionTargetStatus.INSERTED_CORRECT
            ),
            inserted_wrong=sum(
                1
                for result in file_target_results
                if result.status == MypyInsertionTargetStatus.INSERTED_WRONG
            ),
            not_inserted=sum(
                1
                for result in file_target_results
                if result.status == MypyInsertionTargetStatus.NOT_INSERTED
            ),
            parsed=True,
            inferred_by_category=inferred_counts,
            inserted_by_category=_category_counts(inserted),
            correct_by_category=_category_counts(matched),
            inferred_distinct_by_category=_distinct_name_counts(candidates),
            inserted_distinct_by_category=_distinct_name_counts(inserted),
            correct_distinct_by_category=_distinct_name_counts(matched),
            variable_drop_reasons=drop_reasons,
        )
    except Exception as exc:
        return _all_not_inserted(
            rel,
            MypyInsertionFileStatus.RUN_ERROR,
            file_manifest.targets,
            run_error=f"{type(exc).__name__}: {exc}",
        )
    return file_result, file_target_results


def _drive_insertion(
    workspace: Path,
    *,
    make_bridge: Callable[[], ClientBridge],
    journal_path: Path | None,
    max_files: int | None,
) -> MypyInsertionResults:
    """Shared insertion driver: run every eligible file through one server process.

    Results are reassembled in eligible-file order, because resume replays journaled
    files ahead of the pending ones. ``make_bridge()`` builds the single ``ClientBridge``
    the run drives.
    """
    preparation = _load_preparation_result(workspace)
    original_dir = Path(preparation.original_dir)
    stripped_dir = Path(preparation.stripped_dir)

    journaled = _load_journal(journal_path) if journal_path is not None else {}
    if journaled:
        print(f"↩ Resuming from journal: {len(journaled)} file(s) already done ({journal_path})")

    all_eligible = [
        manifest
        for manifest in preparation.files
        if manifest.had_annotations and manifest.preparation_error is None
    ]
    eligible_files = all_eligible if max_files is None else all_eligible[:max_files]
    total_files = len(eligible_files)
    total_targets = sum(len(manifest.targets) for manifest in eligible_files)

    computed: dict[str, tuple[MypyInsertionFileResult, list[MypyInsertionTargetResult]]] = {}
    pending: list[MypyFileManifest] = []
    done = 0
    done_targets = 0
    correct_so_far = 0
    for file_manifest in eligible_files:
        rel = file_manifest.relative_path
        if rel in journaled:
            computed[rel] = journaled[rel]
            done += 1
            done_targets += len(file_manifest.targets)
            correct_so_far += journaled[rel][0].inserted_correct
            print(
                f"[{done}/{total_files}] {rel} ({len(file_manifest.targets)} targets) ↩ journal",
                flush=True,
            )
        else:
            pending.append(file_manifest)

    def insert(
        bridge: ClientBridge, file_manifest: MypyFileManifest, _index: int
    ) -> tuple[MypyInsertionFileResult, list[MypyInsertionTargetResult]]:
        return _insert_file(bridge, file_manifest, original_dir, stripped_dir)

    def report(
        _index: int,
        file_manifest: MypyFileManifest,
        result: tuple[MypyInsertionFileResult, list[MypyInsertionTargetResult]] | None,
    ) -> None:
        nonlocal done, done_targets, correct_so_far
        if result is None:
            return
        file_result, file_target_results = result
        computed[file_manifest.relative_path] = result
        done += 1
        done_targets += file_result.total_targets
        correct_so_far += file_result.inserted_correct
        overall_pct = (correct_so_far / done_targets * 100) if done_targets else 0.0
        if file_result.status == MypyInsertionFileStatus.OK:
            detail = (
                f"✓ {file_result.inserted_correct}/{file_result.total_targets} inserted-correct · "
                f"{done_targets}/{total_targets} targets done · {overall_pct:.1f}% yield overall"
            )
        else:
            err = f": {file_result.run_error}" if file_result.run_error else ""
            detail = f"✗ {file_result.status.value}{err}"
        print(
            f"[{done}/{total_files}] {file_manifest.relative_path} "
            f"({file_result.total_targets} targets) {detail}",
            flush=True,
        )
        if journal_path is not None:
            _append_journal(journal_path, file_result, file_target_results)

    map_over_bridge(
        pending,
        make_bridge=make_bridge,
        fn=insert,
        on_done=report,
    )

    file_results = [computed[manifest.relative_path][0] for manifest in eligible_files]
    target_results: list[MypyInsertionTargetResult] = []
    for manifest in eligible_files:
        target_results.extend(computed[manifest.relative_path][1])

    return MypyInsertionResults(
        mypy_revision=preparation.mypy_revision,
        workspace=str(workspace),
        manifest_path=preparation.manifest_path,
        eligible_files=len(all_eligible),
        file_results=file_results,
        target_results=target_results,
    )


def run_mypy_insertion_benchmark(
    workspace: Path,
    journal_path: Path | None = None,
    engine: str = "jedi",
    max_files: int | None = None,
) -> MypyInsertionResults:
    """Run the mypy insertion benchmark from a prepared workspace."""
    return _drive_insertion(
        workspace,
        make_bridge=lambda: ClientBridge(engine=engine, timeout=_LSP_REQUEST_TIMEOUT),
        journal_path=journal_path,
        max_files=max_files,
    )


def as_json(results: MypyInsertionResults) -> dict[str, object]:
    """Convert benchmark results to a JSON-serializable payload."""
    payload = asdict(results)
    payload["file_results"] = [
        {**file_result, "status": file_result["status"].value}
        for file_result in payload["file_results"]
    ]
    payload["target_results"] = [
        {**target, "status": target["status"].value} for target in payload["target_results"]
    ]
    return payload
