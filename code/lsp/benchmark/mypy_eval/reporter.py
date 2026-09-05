"""Summarize and export outputs for the mypy restoration benchmark."""

import json
from collections import defaultdict
from pathlib import Path
from typing import cast

from benchmark.mypy_eval.insertion_runner import (
    _FACT_CATEGORIES,
    MypyInsertionFileStatus,
    MypyInsertionResults,
)
from benchmark.mypy_eval.insertion_runner import as_json as insertion_as_json
from benchmark.mypy_eval.normalizer import base_head
from benchmark.mypy_eval.runner import MypyBenchmarkResults, MypyTargetStatus, as_json

_AUTHOR_INTENT_ANNOTATIONS = frozenset({"Final", "_TypeAlias"})


def is_author_intent_annotation(normalized_expected: str) -> bool:
    """Ground truths that encode author intent rather than derivable type facts.

    ``Final``/``Final[...]`` carries a mutability policy and ``_TypeAlias`` marks a
    type alias, and neither is a fact about a value that an engine reading the code
    could recover. They are excluded from the adjusted accuracy metric.

    ``object`` used to be excluded here on the same reasoning, and the corpus
    contradicted it. Of its 124 ground truths, 44 are function returns and Fangtype
    infers every one of them correctly, so the exclusion was dropping a result the
    engine had earned rather than an unreachable one.
    """
    return normalized_expected in _AUTHOR_INTENT_ANNOTATIONS or normalized_expected.startswith(
        "Final["
    )


def is_unreachable_final(normalized_expected: str) -> bool:
    """Ground truth is the bare ``Final`` qualifier — a constancy marker, not a type.

    No inference engine can ever emit this from reading the code, so it is
    unreachable by construction. This is a narrower, exact-match rule than
    :func:`is_author_intent_annotation`: ``Final[X]`` still carries a concrete
    value type (``X``) that an engine could in principle infer, so it is
    intentionally NOT considered unreachable here.
    """
    return normalized_expected == "Final"


def is_partial_match(normalized_expected: str, normalized_inferred: str | None) -> bool:
    """Base-type-only match: inferred is the bare generic base of a more specific
    (parameterized) expected type.

    Strict: the inferred type must be an un-parameterized name equal to the expected
    type's outermost generic base, and the expected type must be parameterized (i.e.
    differ from the inferred bare name). e.g. inferred ``Callable`` vs expected
    ``Callable[[X], Y]`` -> True. Both-parameterized cases (``list[int]`` vs
    ``list[str]``), unions (``int`` vs ``int | None``), and inferred-more-specific
    (``list[int]`` vs ``list``) stay full mismatches.

    When ``base_head(expected) == inferred`` and ``expected != inferred``, the expected
    annotation is necessarily the subscripted form — so no separate "is subscripted"
    check is required.
    """
    if normalized_inferred is None or normalized_inferred == normalized_expected:
        return False
    return base_head(normalized_expected) == normalized_inferred


def summarize(results: MypyBenchmarkResults) -> str:
    """One plain-text block describing a finished restoration run.

    The committed artefact is the JSON that ``export_json`` writes, and every figure
    the thesis cites is recomputed from ``target_results`` by
    ``thesis/evaluation/generate_tables.py``. This exists so that an operator watching
    a run that takes minutes can see what it produced without opening the JSON, so it
    stays a summary and never becomes a second source of truth.
    """
    targets = results.target_results
    total = len(targets)

    counts: dict[MypyTargetStatus, int] = defaultdict(int)
    for target in targets:
        counts[target.status] += 1
    matched = counts[MypyTargetStatus.MATCH]

    def pct(value: int) -> float:
        return (value / total * 100) if total else 0.0

    excluded = [
        target
        for target in targets
        if is_author_intent_annotation(target.normalized_expected_annotation)
    ]
    adjusted_total = total - len(excluded)
    adjusted_matched = matched - sum(
        1 for target in excluded if target.status == MypyTargetStatus.MATCH
    )
    adjusted_pct = (adjusted_matched / adjusted_total * 100) if adjusted_total else 0.0

    partial = sum(
        1
        for target in targets
        if target.status == MypyTargetStatus.MISMATCH
        and is_partial_match(
            target.normalized_expected_annotation,
            target.normalized_inferred_annotation,
        )
    )

    lines = [
        f"Targets            {total}",
        f"Matched            {matched} ({pct(matched):.1f}%)",
        f"Partial base type  {partial} ({pct(partial):.1f}%)",
    ]
    for status in (
        MypyTargetStatus.MISMATCH,
        MypyTargetStatus.INFERENCE_FAILED,
        MypyTargetStatus.INSERTION_FAILED,
        MypyTargetStatus.TIMEOUT,
        MypyTargetStatus.RUN_ERROR,
    ):
        value = counts[status]
        lines.append(f"{status.value:<18} {value} ({pct(value):.1f}%)")
    lines += [
        f"Adjusted accuracy  {adjusted_matched}/{adjusted_total} ({adjusted_pct:.1f}%), "
        f"dropping {len(excluded)} author-intent targets",
        f"Files              {results.typed_files.file_count} annotated, "
        f"{results.untyped_files.file_count} unannotated",
        f"Corpus revision    {results.mypy_revision}",
    ]
    return "\n".join(lines)


def export_json(
    results: MypyBenchmarkResults,
    output_path: Path,
    *,
    engine: str | None = None,
    gate_enabled: bool | None = None,
    resolution_context: str | None = None,
    fangtype_revision: str | None = None,
    toolchain: dict[str, str | bool] | None = None,
) -> None:
    """Export mypy benchmark results to JSON.

    Adds reporting-only fields on top of ``as_json``'s output: per-target
    ``unreachable_final`` / ``partial_match`` booleans, top-level
    ``unreachable_final_targets`` / ``partial_match_targets`` counts, the
    ``engine`` / ``gate_enabled`` pair naming the configuration that produced the run,
    ``resolution_context`` naming the tree cross-module imports resolved against
    (``"annotated"`` or ``"cold"``), ``fangtype_revision`` naming the commit that
    produced it, and ``toolchain`` with the
    Jedi/mypy/CPython versions of the same run plus a ``fangtype_dirty`` flag, since
    ``fangtype_revision`` alone cannot show a working tree that had uncommitted changes.
    Artefacts exported before ``fangtype_dirty`` existed simply omit that key rather than
    carrying a guessed value.
    All are additive — every existing field/value is untouched, so archived baselines
    stay comparable.
    """
    payload = as_json(results)
    if engine is not None:
        payload["engine"] = engine
    if gate_enabled is not None:
        payload["gate_enabled"] = gate_enabled
    # The annotated and cold artefacts are schema-identical and are told apart only by the
    # filename an operator types, exactly like the gate pair.
    if resolution_context is not None:
        payload["resolution_context"] = resolution_context
    if fangtype_revision is not None:
        payload["fangtype_revision"] = fangtype_revision
    if toolchain is not None:
        payload.update(toolchain)
    target_payloads = cast("list[dict[str, object]]", payload["target_results"])
    for target_payload, target in zip(target_payloads, results.target_results, strict=True):
        target_payload["unreachable_final"] = is_unreachable_final(
            target.normalized_expected_annotation
        )
        target_payload["partial_match"] = (
            target.status == MypyTargetStatus.MISMATCH
            and is_partial_match(
                target.normalized_expected_annotation,
                target.normalized_inferred_annotation,
            )
        )
    payload["unreachable_final_targets"] = sum(
        1
        for target in results.target_results
        if is_unreachable_final(target.normalized_expected_annotation)
    )
    payload["partial_match_targets"] = sum(
        1
        for target in results.target_results
        if target.status == MypyTargetStatus.MISMATCH
        and is_partial_match(
            target.normalized_expected_annotation,
            target.normalized_inferred_annotation,
        )
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"✓ Exported mypy benchmark results to {output_path}")


# --- Insertion benchmark reporting -----------------------------------------------
#
# Companion to the section above: where the restoration run asks "did inference
# recover the right type?", this one asks "did the real insert path actually WORK
# (parse-clean output) and COMPILE (no new mypy errors)?".


def _aggregate_funnel(
    results: MypyInsertionResults,
) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    """Sum the per-file inference -> insertion funnel counts across every file.

    Returns ``(inferred, inserted, correct)`` dicts keyed by fact category. ``inferred``
    is the fidelity denominator (types the server would annotate), ``inserted`` is what
    landed with any type, ``correct`` is what landed carrying the inferred type intact.
    """
    inferred: dict[str, int] = defaultdict(int)
    inserted: dict[str, int] = defaultdict(int)
    correct: dict[str, int] = defaultdict(int)
    for file_result in results.file_results:
        for category in _FACT_CATEGORIES:
            inferred[category] += file_result.inferred_by_category.get(category, 0)
            inserted[category] += file_result.inserted_by_category.get(category, 0)
            correct[category] += file_result.correct_by_category.get(category, 0)
    return inferred, inserted, correct


def summarize_insertion(results: MypyInsertionResults) -> str:
    """One plain-text block describing a finished insertion run.

    Same contract as :func:`summarize`. The numbers behind the thesis come from the
    JSON, not from here.
    """
    inferred, inserted, correct = _aggregate_funnel(results)
    total_inferred = sum(inferred.values())
    total_inserted = sum(inserted.values())
    total_correct = sum(correct.values())

    def pct(value: int) -> float:
        return (value / total_inferred * 100) if total_inferred else 0.0

    file_counts: dict[MypyInsertionFileStatus, int] = defaultdict(int)
    for file_result in results.file_results:
        file_counts[file_result.status] += 1

    lines = [
        f"Eligible files     {results.eligible_files}",
        f"Inferred           {total_inferred}",
        f"Inserted           {total_inserted} ({pct(total_inserted):.1f}%)",
        f"Correct            {total_correct} ({pct(total_correct):.1f}%)",
    ]
    for category in _FACT_CATEGORIES:
        lines.append(
            f"  {category:<16} {correct[category]}/{inferred[category]} correct, "
            f"{inserted[category]} inserted"
        )
    for status in MypyInsertionFileStatus:
        lines.append(f"{status.value:<18} {file_counts[status]} files")
    lines.append(f"Corpus revision    {results.mypy_revision}")
    return "\n".join(lines)


def export_insertion_json(
    results: MypyInsertionResults,
    output_path: Path,
    *,
    engine: str | None = None,
    gate_enabled: bool | None = None,
    resolution_context: str | None = None,
    fangtype_revision: str | None = None,
    toolchain: dict[str, str | bool] | None = None,
) -> None:
    """Export mypy insertion benchmark results to JSON.

    ``engine`` and ``gate_enabled`` name the configuration. The gate-on and gate-off
    artefacts of this mode are schema-identical, so the pair is what tells them apart
    once the filename is out of sight. ``fangtype_revision`` names the commit that
    produced the run, and ``toolchain`` carries its Jedi/mypy/CPython versions plus a
    ``fangtype_dirty`` flag for what ``fangtype_revision`` alone cannot show, namely an
    uncommitted change on top of that commit. Artefacts exported before that flag
    existed simply omit the key rather than carrying a guessed value.
    """
    payload = insertion_as_json(results)
    if engine is not None:
        payload["engine"] = engine
    if gate_enabled is not None:
        payload["gate_enabled"] = gate_enabled
    # Which tree the run resolved imports against, matching the restore export. Nothing
    # else in the artefact records it, so without this an auditor cannot tell a run that
    # resolved against corpus source from one that fell through to site-packages.
    if resolution_context is not None:
        payload["resolution_context"] = resolution_context
    if fangtype_revision is not None:
        payload["fangtype_revision"] = fangtype_revision
    if toolchain is not None:
        payload.update(toolchain)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"✓ Exported mypy insertion benchmark results to {output_path}")
