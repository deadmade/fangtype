"""Generate markdown reports and export JSON for the official-scoring inference run."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from benchmark.typeevalpy.inference_runner import InferenceScore
    from benchmark.typeevalpy.insertion_runner import InsertionScore


def generate_report(
    score: InferenceScore | InsertionScore,
    *,
    title: str = "TypeEvalPy Inference Benchmark -- OFFICIAL scoring",
    subtitle: str = (
        "(recall over ground-truth facts, col_offset-insensitive matching, via the "
        "vendored TypeEvalPy submodule scorer)"
    ),
    exact_label: str = "Exact match (recall)",
    partial_label: str = "Partial match",
    sound_label: str = "Sound (no false negatives)",
    complete_label: str = "Complete (no false positives)",
    complete_total: int | None = None,
) -> str:
    """Generate a markdown report of a scoring run."""
    lines = [
        f"# {title}",
        "",
        subtitle,
        "",
        f"Tool: `{score.tool_name}` | Files: {score.file_count} | Results: `{score.out_root}`",
        "",
        f"{exact_label}: {score.num_caught_exact}/{score.num_all} ({score.exact_pct:.1f}%)",
        f"{partial_label}: {score.num_caught_partial}/{score.num_all}",
        "",
        "## By category",
        "",
        "| Category | Caught | Total | Pct |",
        "|----------|--------|-------|-----|",
    ]

    for cat, stats in score.per_category.items():
        total = stats["num_all"]
        caught = stats["num_caught_exact"]
        pct = (caught / total * 100) if total else 0.0
        lines.append(f"| {cat} | {caught} | {total} | {pct:.1f}% |")

    complete_denom = complete_total if complete_total is not None else score.file_count
    lines += [
        "",
        f"{sound_label}: {score.sound_count}/{score.file_count} files",
        f"{complete_label}: {score.complete_count}/{complete_denom} files",
        "",
    ]

    return "\n".join(lines)


def generate_comparison(fangtype: InferenceScore, reference: InferenceScore) -> str:
    """Generate a markdown side-by-side comparison of two ``InferenceScore``s."""
    delta = fangtype.exact_pct - reference.exact_pct
    lines = [
        f"## {fangtype.tool_name} vs {reference.tool_name} (reference)",
        "",
        "| Tool | Exact match | exact_pct |",
        "|------|-------------|-----------|",
        f"| {fangtype.tool_name} | {fangtype.num_caught_exact}/{fangtype.num_all} "
        f"| {fangtype.exact_pct:.2f}% |",
        f"| {reference.tool_name} | {reference.num_caught_exact}/{reference.num_all} "
        f"| {reference.exact_pct:.2f}% |",
        "",
        f"Delta ({fangtype.tool_name} - {reference.tool_name}): {delta:+.2f} pp",
    ]
    return "\n".join(lines)


def generate_lenient_companion(strict: InferenceScore, lenient: InferenceScore) -> str:
    """Render the concept-lenient companion block alongside the strict headline score.

    The companion credits non-insertable ``generator``/``code`` predictions (the runtime
    ``types`` names the tool honestly emits) against TypeEvalPy's bare ground-truth spellings.
    It is explicitly labeled NOT-insertable and shown only for transparency -- the delta is
    exactly what the generator/code cases add on top of the strict/insertable recall.
    """
    caught_delta = lenient.num_caught_exact - strict.num_caught_exact
    pp_delta = lenient.exact_pct - strict.exact_pct
    lines = [
        "## Concept-lenient companion (NOT insertable -- shown for transparency)",
        "",
        "Credits non-insertable `generator`/`code` predictions against TypeEvalPy's bare "
        "ground-truth spellings. These are NOT valid, insertable annotations; this metric "
        "only shows how much the generator/code cases add on top of the strict headline.",
        "",
        f"Strict (insertable) exact recall: {strict.num_caught_exact}/{strict.num_all} "
        f"({strict.exact_pct:.1f}%)",
        f"Concept-lenient exact recall: {lenient.num_caught_exact}/{lenient.num_all} "
        f"({lenient.exact_pct:.1f}%)",
        f"Delta (lenient - strict): +{caught_delta} facts ({pp_delta:+.1f} pp)",
        "",
    ]
    return "\n".join(lines)


def export_json(score: InferenceScore | InsertionScore, output_path: Path) -> None:
    """Export the ``InferenceScore`` fields (plus ``exact_pct``) as JSON."""
    data = asdict(score)
    data["out_root"] = str(score.out_root)
    data["exact_pct"] = score.exact_pct

    output_path.write_text(json.dumps(data, indent=2))
    print(f"Exported detailed results to {output_path}")
