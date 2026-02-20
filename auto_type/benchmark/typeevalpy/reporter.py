"""Generate markdown reports and export JSON."""

import json
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from benchmark.typeevalpy.runner import BenchmarkResults, InferenceResult


def generate_summary_section(results: BenchmarkResults) -> str:
    """Generate summary table with key metrics."""

    correct_count = len(results.correct)
    incorrect_count = len(results.incorrect)
    unsupported_count = len(results.unsupported)
    out_of_scope_count = len(results.out_of_scope)
    total = results.total

    attempted = correct_count + incorrect_count
    accuracy = (correct_count / attempted * 100) if attempted > 0 else 0

    return f"""## Summary

| Metric | Count | Percentage |
|--------|-------|------------|
| Total annotations | {total} | 100.0% |
| ✅ Correct | {correct_count} | {correct_count / total * 100:.1f}% |
| ❌ Incorrect | {incorrect_count} | {incorrect_count / total * 100:.1f}% |
| ⚠️ Unsupported (variables) | {unsupported_count} | {unsupported_count / total * 100:.1f}% |
| 🔵 Out of scope | {out_of_scope_count} | {out_of_scope_count / total * 100:.1f}% |

**Current Coverage:** {correct_count} / {total} ({correct_count / total * 100:.1f}%)
**Accuracy on Attempted:** {correct_count} / {attempted} ({accuracy:.1f}%)
"""


def generate_type_breakdown(results: BenchmarkResults) -> str:
    """Generate breakdown by inferred type."""

    # Group results by expected type
    type_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"correct": 0, "total": 0})

    for result in results.correct:
        typ = result.inferred_type
        if typ is not None:
            type_stats[typ]["correct"] += 1
            type_stats[typ]["total"] += 1

    for result in results.incorrect:
        # Use expected type (since inference was wrong)
        typ = result.case.expected_types[0]  # Use first expected type
        type_stats[typ]["total"] += 1

    if not type_stats:
        return "## By Type\n\nNo type-specific data available.\n"

    # Format as table
    lines = [
        "## By Type",
        "",
        "| Type | Correct | Total | Accuracy |",
        "|------|---------|-------|----------|",
    ]

    for typ in sorted(type_stats.keys()):
        stats = type_stats[typ]
        accuracy = (stats["correct"] / stats["total"] * 100) if stats["total"] > 0 else 0
        lines.append(f"| {typ} | {stats['correct']} | {stats['total']} | {accuracy:.1f}% |")

    return "\n".join(lines)


def generate_failure_examples(results: BenchmarkResults, max_examples: int = 10) -> str:
    """Show examples of incorrect inferences."""

    if not results.incorrect:
        return ""

    lines = ["## Incorrect Inferences", "", f"Showing up to {max_examples} examples:", ""]

    for i, result in enumerate(results.incorrect[:max_examples], 1):
        case = result.case
        lines.append(
            f"{i}. `{case.category}/{case.file_path.name}:{case.line_number}` - "
            f"Variable `{case.variable_name}`: "
            f"Expected `{', '.join(case.expected_types)}`, Got `{result.inferred_type}`"
        )

    if len(results.incorrect) > max_examples:
        lines.append(f"\n... and {len(results.incorrect) - max_examples} more")

    return "\n".join(lines)


def generate_unsupported_list(results: BenchmarkResults) -> str:
    """Generate simple list of unsupported patterns."""

    lines = ["## Unsupported Patterns", ""]

    # Group by failure reason
    pattern_counts: dict[str, int] = defaultdict(int)
    for result in results.unsupported:
        if result.reason is not None:
            pattern_counts[result.reason] += 1

    if not pattern_counts:
        lines.append("No unsupported patterns found.")
        return "\n".join(lines)

    # Sort by count descending
    sorted_patterns = sorted(pattern_counts.items(), key=lambda x: x[1], reverse=True)

    lines.append("| Pattern | Count |")
    lines.append("|---------|-------|")

    for pattern, count in sorted_patterns:
        lines.append(f"| {pattern} | {count} |")

    lines.append("")
    return "\n".join(lines)


def generate_report(results: BenchmarkResults) -> str:
    """Generate complete markdown report."""

    sections = [
        "# TypeEvalPy Benchmark Results",
        "",
        generate_summary_section(results),
        "",
        generate_failure_examples(results),
        "",
        generate_unsupported_list(results),
        "",
    ]

    return "\n".join(sections)


def export_json(results: BenchmarkResults, output_path: Path) -> None:
    """Export detailed results as JSON."""

    def result_to_dict(r: InferenceResult) -> dict[str, object]:
        return {
            "file": str(r.case.file_path),
            "line": r.case.line_number,
            "variable": r.case.variable_name,
            "expected": r.case.expected_types,
            "inferred": r.inferred_type,
            "status": r.status.value,
            "reason": r.reason,
            "category": r.case.category,
        }

    data = {
        "summary": {
            "total": results.total,
            "correct": len(results.correct),
            "incorrect": len(results.incorrect),
            "unsupported": len(results.unsupported),
            "out_of_scope": len(results.out_of_scope),
        },
        "correct": [result_to_dict(r) for r in results.correct],
        "incorrect": [result_to_dict(r) for r in results.incorrect],
        "unsupported": [result_to_dict(r) for r in results.unsupported],
        "out_of_scope": [result_to_dict(r) for r in results.out_of_scope],
    }

    output_path.write_text(json.dumps(data, indent=2))
    print(f"Exported detailed results to {output_path}")
