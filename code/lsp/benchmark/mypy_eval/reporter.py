"""Generate reports and export outputs for the mypy restoration benchmark."""

import json
from collections import defaultdict
from pathlib import Path
from typing import cast

from benchmark.mypy_eval.insertion_runner import (
    _FACT_CATEGORIES,
    MypyInsertionFileStatus,
    MypyInsertionResults,
    MypyInsertionTargetStatus,
)
from benchmark.mypy_eval.insertion_runner import as_json as insertion_as_json
from benchmark.mypy_eval.normalizer import base_head
from benchmark.mypy_eval.runner import MypyBenchmarkResults, MypyTargetStatus, as_json

_AUTHOR_INTENT_ANNOTATIONS = frozenset({"Final", "_TypeAlias", "object"})


def is_author_intent_annotation(normalized_expected: str) -> bool:
    """Ground truths that encode author intent rather than derivable type facts.

    ``Final``/``Final[...]`` (mutability policy), ``_TypeAlias`` markers, and
    deliberate ``object`` widenings cannot be produced by any inference engine
    reading the code; they are excluded from the adjusted accuracy metric.
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


def generate_summary_section(results: MypyBenchmarkResults) -> str:
    """Generate the overall summary table."""
    targets = results.target_results
    total = len(targets)

    counts: dict[MypyTargetStatus, int] = defaultdict(int)
    for target in targets:
        counts[target.status] += 1

    matched = counts[MypyTargetStatus.MATCH]
    mismatched = counts[MypyTargetStatus.MISMATCH]
    inference_failed = counts[MypyTargetStatus.INFERENCE_FAILED]
    insertion_failed = counts[MypyTargetStatus.INSERTION_FAILED]
    run_error = counts[MypyTargetStatus.RUN_ERROR]
    timeout = counts[MypyTargetStatus.TIMEOUT]

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

    unreachable_final = sum(
        1 for target in targets if is_unreachable_final(target.normalized_expected_annotation)
    )

    partial = sum(
        1
        for target in targets
        if target.status == MypyTargetStatus.MISMATCH
        and is_partial_match(
            target.normalized_expected_annotation,
            target.normalized_inferred_annotation,
        )
    )
    # Base-type partials are carved out of the mismatch bucket into their own row, so the
    # mutually-exclusive rows still sum to 100%. The headline accuracy stays MATCH-only.
    strict_mismatched = mismatched - partial
    lenient = matched + partial

    return f"""## Summary

| Metric | Count | Percentage |
|--------|-------|------------|
| Total targets | {total} | 100.0% |
| ✅ Matched | {matched} | {pct(matched):.1f}% |
| ❌ Mismatched | {strict_mismatched} | {pct(strict_mismatched):.1f}% |
| 🟡 Partial (base type) | {partial} | {pct(partial):.1f}% |
| ⚠️ Inference failed | {inference_failed} | {pct(inference_failed):.1f}% |
| 💥 Insertion failed | {insertion_failed} | {pct(insertion_failed):.1f}% |
| ⏱️ Timeout | {timeout} | {pct(timeout):.1f}% |
| 🧨 Run error | {run_error} | {pct(run_error):.1f}% |

**Overall accuracy: {matched}/{total} ({pct(matched):.1f}%)**
**Adjusted accuracy: {adjusted_matched}/{adjusted_total} ({adjusted_pct:.1f}%)** — excludes \
{len(excluded)} author-intent targets (`Final`/`Final[...]`, `_TypeAlias`, `object` ground \
truths that no inference engine can derive from the code)
**Partial (base type) matches: {partial}/{total} ({pct(partial):.1f}%)** — correct base \
generic but missing type arguments (e.g. `Callable` for `Callable[..., None]`); carved out of \
the mismatch bucket into their own row above, still excluded from the headline accuracy.
**Lenient accuracy (exact + partial base type): {lenient}/{total} ({pct(lenient):.1f}%)** — \
companion metric only, NOT the headline; credits base-type-correct inferences.

Unreachable ground truth (bare Final qualifier): {unreachable_final} targets \
({pct(unreachable_final):.1f}% of total) — these remain scored as mismatches/failures above; \
this line only annotates that no engine can ever produce the bare `Final` qualifier.

Files: {results.typed_files.file_count} annotated, {results.untyped_files.file_count} unannotated
Revision: {results.mypy_revision}
"""


def generate_kind_breakdown(results: MypyBenchmarkResults) -> str:
    """Generate accuracy broken down by target kind."""
    stats: dict[str, dict[str, int]] = defaultdict(lambda: {"matched": 0, "total": 0})
    for target in results.target_results:
        stats[target.target_kind]["total"] += 1
        if target.status == MypyTargetStatus.MATCH:
            stats[target.target_kind]["matched"] += 1

    if not stats:
        return "## By Target Kind\n\nNo targets.\n"

    lines = [
        "## By Target Kind",
        "",
        "| Kind | Matched | Total | Accuracy |",
        "|------|---------|-------|----------|",
    ]
    for kind in sorted(stats):
        entry = stats[kind]
        accuracy = (entry["matched"] / entry["total"] * 100) if entry["total"] else 0.0
        lines.append(f"| {kind} | {entry['matched']} | {entry['total']} | {accuracy:.1f}% |")

    return "\n".join(lines)


def generate_mismatch_examples(results: MypyBenchmarkResults, max_examples: int = 10) -> str:
    """Show a handful of expected-vs-inferred mismatches."""
    mismatches = [
        target for target in results.target_results if target.status == MypyTargetStatus.MISMATCH
    ]
    if not mismatches:
        return ""

    lines = [f"## Mismatch Examples (showing up to {max_examples})", ""]
    for target in mismatches[:max_examples]:
        lines.append(
            f"- **{target.relative_path}:{target.line_number}** "
            f"`{target.identifier}` ({target.target_kind})"
        )
        lines.append(f"  - Expected: `{target.expected_annotation}`")
        lines.append(f"  - Inferred: `{target.inferred_annotation}`")
        lines.append("")

    return "\n".join(lines)


def generate_partial_examples(results: MypyBenchmarkResults, max_examples: int = 10) -> str:
    """Show a handful of base-type partial matches (correct base, missing type args)."""
    partials = [
        target
        for target in results.target_results
        if target.status == MypyTargetStatus.MISMATCH
        and is_partial_match(
            target.normalized_expected_annotation,
            target.normalized_inferred_annotation,
        )
    ]
    if not partials:
        return ""

    lines = [f"## Partial (base type) Examples (showing up to {max_examples})", ""]
    for target in partials[:max_examples]:
        lines.append(
            f"- **{target.relative_path}:{target.line_number}** "
            f"`{target.identifier}` ({target.target_kind})"
        )
        lines.append(f"  - Expected: `{target.expected_annotation}`")
        lines.append(f"  - Inferred: `{target.inferred_annotation}`")
        lines.append("")

    return "\n".join(lines)


def generate_report(results: MypyBenchmarkResults) -> str:
    """Generate the complete mypy restoration benchmark report as markdown."""
    sections = [
        "# Mypy Restoration Benchmark Report",
        "",
        generate_summary_section(results),
        "",
        generate_kind_breakdown(results),
        "",
        generate_mismatch_examples(results),
        "",
        generate_partial_examples(results),
    ]
    return "\n".join(sections)


def export_json(results: MypyBenchmarkResults, output_path: Path) -> None:
    """Export mypy benchmark results to JSON.

    Adds reporting-only fields on top of ``as_json``'s output: per-target
    ``unreachable_final`` / ``partial_match`` booleans and top-level
    ``unreachable_final_targets`` / ``partial_match_targets`` counts. All are
    additive — every existing field/value is untouched, so archived baselines
    stay comparable.
    """
    payload = as_json(results)
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
# Companion to the section above: where the restoration report asks "did inference
# recover the right type?", this one asks "did the real insert path actually WORK
# (parse-clean output) and COMPILE (no new mypy errors)?". Additive only — none of
# the restoration-report functions above are touched.


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


def _aggregate_distinct_funnel(
    results: MypyInsertionResults,
) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    """Sum the *distinct-name* funnel counts across every file.

    Same shape as ``_aggregate_funnel`` but over the per-name-deduped counts: reassigned
    variables (several bindings, one legal annotation site) collapse to one, so this
    denominator isn't inflated by flow-sensitive duplicates a single insert can't satisfy.
    """
    inferred: dict[str, int] = defaultdict(int)
    inserted: dict[str, int] = defaultdict(int)
    correct: dict[str, int] = defaultdict(int)
    for file_result in results.file_results:
        for category in _FACT_CATEGORIES:
            inferred[category] += file_result.inferred_distinct_by_category.get(category, 0)
            inserted[category] += file_result.inserted_distinct_by_category.get(category, 0)
            correct[category] += file_result.correct_distinct_by_category.get(category, 0)
    return inferred, inserted, correct


def generate_insertion_summary_section(results: MypyInsertionResults) -> str:
    """Generate the overall summary table for the insertion benchmark."""
    eligible = results.eligible_files
    processed = len(results.file_results)

    file_counts: dict[MypyInsertionFileStatus, int] = defaultdict(int)
    for file_result in results.file_results:
        file_counts[file_result.status] += 1

    ok = file_counts[MypyInsertionFileStatus.OK]
    insertion_failed = file_counts[MypyInsertionFileStatus.INSERTION_FAILED]
    parse_failed = file_counts[MypyInsertionFileStatus.PARSE_FAILED]
    run_error = file_counts[MypyInsertionFileStatus.RUN_ERROR]
    with_edit = ok + parse_failed

    def pct(numerator: int, denominator: int) -> float:
        return (numerator / denominator * 100) if denominator else 0.0

    inferred, inserted, correct = _aggregate_funnel(results)
    inferred_total = sum(inferred.values())
    inserted_total = sum(inserted.values())
    correct_total = sum(correct.values())

    d_inferred, d_inserted, d_correct = _aggregate_distinct_funnel(results)
    d_inferred_total = sum(d_inferred.values())
    d_inserted_total = sum(d_inserted.values())
    d_correct_total = sum(d_correct.values())

    return f"""## Summary

Files processed: {processed} (of {eligible} eligible)

| Metric | Count | Percentage |
|--------|-------|------------|
| Eligible files | {eligible} | 100.0% |
| Files with insertion (edit produced) | {with_edit} | {pct(with_edit, processed):.1f}% |
| Files insertion-failed (no edit) | {insertion_failed} | {pct(insertion_failed, processed):.1f}% |
| Files broken output (parse failed) | {parse_failed} | {pct(parse_failed, processed):.1f}% |
| Files run-error | {run_error} | {pct(run_error, processed):.1f}% |
| Files parse-clean (of files with edit) | {ok} | {pct(ok, with_edit):.1f}% |

**Inferred (types): {inferred_total}**
**Inserted (any type): {inserted_total}/{inferred_total} \
({pct(inserted_total, inferred_total):.1f}%)**
**Inserted w/ inferred type intact (yield): {correct_total}/{inferred_total} \
({pct(correct_total, inferred_total):.1f}%)**

_"Yield" is insertion fidelity: of the types the server INFERRED, how many landed carrying
that same type. Denominated by inferred facts, not the corpus's original annotations — it
isolates the insert path from inference accuracy._

**Distinct-name inferred: {d_inferred_total}**
**Distinct-name inserted (any type): {d_inserted_total}/{d_inferred_total} \
({pct(d_inserted_total, d_inferred_total):.1f}%)**
**Distinct-name yield: {d_correct_total}/{d_inferred_total} \
({pct(d_correct_total, d_inferred_total):.1f}%)**

_The distinct-name funnel collapses per-binding duplicates by (scope, name, kind): a
reassigned variable contributes one name, not one fact per assignment site. It separates
genuine insert loss from the metric artifact of scoring several flow-sensitive types
against the single legal annotation a name can carry._

Revision: {results.mypy_revision}
"""


def generate_insertion_kind_breakdown(results: MypyInsertionResults) -> str:
    """Per-category inference -> insertion funnel: inferred / inserted / correct."""
    inferred, inserted, correct = _aggregate_funnel(results)

    if not sum(inferred.values()):
        return "## By Category (inferred → inserted)\n\nNo inferred facts.\n"

    lines = [
        "## By Category (inferred → inserted)",
        "",
        "| Category | Inferred | Inserted (any) | Correct | Yield |",
        "|----------|----------|----------------|---------|-------|",
    ]
    for category in _FACT_CATEGORIES:
        n_inferred = inferred[category]
        n_inserted = inserted[category]
        n_correct = correct[category]
        yield_pct = (n_correct / n_inferred * 100) if n_inferred else 0.0
        lines.append(
            f"| {category} | {n_inferred} | {n_inserted} | {n_correct} | {yield_pct:.1f}% |"
        )

    d_inferred, d_inserted, d_correct = _aggregate_distinct_funnel(results)
    lines += [
        "",
        "### Distinct-name (per (scope, name, kind), reassignments collapsed)",
        "",
        "| Category | Inferred | Inserted (any) | Correct | Yield |",
        "|----------|----------|----------------|---------|-------|",
    ]
    for category in _FACT_CATEGORIES:
        n_inferred = d_inferred[category]
        n_inserted = d_inserted[category]
        n_correct = d_correct[category]
        yield_pct = (n_correct / n_inferred * 100) if n_inferred else 0.0
        lines.append(
            f"| {category} | {n_inferred} | {n_inserted} | {n_correct} | {yield_pct:.1f}% |"
        )

    return "\n".join(lines)


def generate_insertion_drop_reasons_section(results: MypyInsertionResults) -> str:
    """Per-reason histogram of why surfaced variables were (not) annotated.

    Sums the server's ``variable_drop_reasons`` across files. Scoped taxonomy (insert-path
    observable only): ``selected`` (a valid binding was chosen) vs ``all_mypy_invalid``
    (candidates existed but every binding failed mypy). Names dropped upstream as all-
    ``Unknown``/nonlocal/comprehension/already-annotated are NOT counted here — they are
    "not inferred", not an insert-path drop. Empty section when the server reported none.
    """
    totals: dict[str, int] = defaultdict(int)
    for file_result in results.file_results:
        for reason, count in file_result.variable_drop_reasons.items():
            totals[reason] += count
    if not totals:
        return ""

    lines = [
        "## Variable Miss Attribution (insert-path observable)",
        "",
        "| Reason | Count |",
        "|--------|-------|",
    ]
    for reason in sorted(totals):
        lines.append(f"| {reason} | {totals[reason]} |")
    lines.append("")
    lines.append(
        "_`selected` = a mypy-valid binding was chosen; `all_mypy_invalid` = candidates "
        "existed but every binding failed mypy. Names with only `Unknown`/nonlocal/"
        "comprehension/already-annotated bindings never enter candidates and are counted "
        "upstream as 'not inferred', not here._"
    )
    return "\n".join(lines)


def generate_insertion_mismatch_examples(
    results: MypyInsertionResults, max_examples: int = 10
) -> str:
    """Show a handful of targets where the wrong type was inserted."""
    mismatches = [
        target
        for target in results.target_results
        if target.status == MypyInsertionTargetStatus.INSERTED_WRONG
    ]
    if not mismatches:
        return ""

    lines = [f"## Insertion Mismatch Examples (showing up to {max_examples})", ""]
    for target in mismatches[:max_examples]:
        lines.append(
            f"- **{target.relative_path}:{target.line_number}** "
            f"`{target.identifier}` ({target.target_kind})"
        )
        lines.append(f"  - Expected: `{target.expected_annotation}`")
        lines.append(f"  - Inserted: `{target.inserted_annotation}`")
        lines.append("")

    return "\n".join(lines)


def generate_insertion_report(results: MypyInsertionResults) -> str:
    """Generate the complete mypy insertion benchmark report as markdown."""
    sections = [
        "# Mypy Insertion Benchmark Report",
        "",
        generate_insertion_summary_section(results),
        "",
        generate_insertion_kind_breakdown(results),
        "",
        generate_insertion_drop_reasons_section(results),
        "",
        generate_insertion_mismatch_examples(results),
    ]
    return "\n".join(sections)


def export_insertion_json(results: MypyInsertionResults, output_path: Path) -> None:
    """Export mypy insertion benchmark results to JSON."""
    payload = insertion_as_json(results)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"✓ Exported mypy insertion benchmark results to {output_path}")
