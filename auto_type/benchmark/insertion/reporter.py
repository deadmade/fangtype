"""Generate reports and export results for insertion benchmark.

This module provides functions to generate human-readable reports and export
JSON results from insertion benchmark runs.
"""

import json
from collections import defaultdict
from typing import TYPE_CHECKING

from benchmark.insertion.runner import InsertionBenchmarkResults, InsertionStatus

if TYPE_CHECKING:
    from pathlib import Path


def generate_summary_section(results: InsertionBenchmarkResults) -> str:
    """Generate summary table with key metrics.

    Args:
        results: Insertion benchmark results

    Returns:
        Formatted summary section as markdown
    """
    correct_count = len(results.correct)
    type_mismatch_count = len(results.type_mismatch)
    insertion_failed_count = len(results.insertion_failed)
    inference_failed_count = len(results.inference_failed)
    syntax_error_count = len(results.syntax_errors)
    annotation_missing_count = len(results.annotation_missing)
    not_applicable_count = len(results.not_applicable)
    total = results.total

    # Calculate pipeline success rates (excluding not_applicable cases)
    applicable_total = total - not_applicable_count
    inference_attempted = applicable_total
    inference_succeeded = applicable_total - inference_failed_count
    inference_rate = (
        (inference_succeeded / inference_attempted * 100) if inference_attempted > 0 else 0
    )

    insertion_attempted = inference_succeeded
    insertion_succeeded = correct_count + type_mismatch_count
    insertion_rate = (
        (insertion_succeeded / insertion_attempted * 100) if insertion_attempted > 0 else 0
    )

    end_to_end_rate = (correct_count / applicable_total * 100) if applicable_total > 0 else 0

    return f"""## Summary

| Metric | Count | Percentage |
|--------|-------|------------|
| Total cases | {total} | 100.0% |
| ✅ Correct insertions | {correct_count} | {correct_count / total * 100:.1f}% |
| ❌ Type mismatches | {type_mismatch_count} | {type_mismatch_count / total * 100:.1f}% |
| ⚠️ Inference failures | {inference_failed_count} | {inference_failed_count / total * 100:.1f}% |
| 💥 Insertion failures | {insertion_failed_count} | {insertion_failed_count / total * 100:.1f}% |
| 🔍 Syntax errors | {syntax_error_count} | {syntax_error_count / total * 100:.1f}% |
| 📝 Missing | {annotation_missing_count} | {annotation_missing_count / total * 100:.1f}% |
### Pipeline Success Rates (applicable cases only)

| Stage | Success Rate |
|-------|-------------|
| Inference (Jedi) | {inference_succeeded}/{inference_attempted} ({inference_rate:.1f}%) |
| Insertion | {insertion_succeeded}/{insertion_attempted} ({insertion_rate:.1f}%) |
| End-to-end | {correct_count}/{applicable_total} ({end_to_end_rate:.1f}%) |
"""


def generate_category_breakdown(results: InsertionBenchmarkResults) -> str:
    """Generate breakdown by TypeEvalPy category.

    Args:
        results: Insertion benchmark results

    Returns:
        Formatted category breakdown as markdown
    """
    # Group results by category
    category_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"correct": 0, "total": 0})

    for result in results.results:
        category = result.case.category.split("/")[0]  # Top-level category
        category_stats[category]["total"] += 1
        if result.status == InsertionStatus.CORRECT:
            category_stats[category]["correct"] += 1

    if not category_stats:
        return "## By Category\n\nNo category data available.\n"

    # Format as table
    lines = [
        "## By Category",
        "",
        "| Category | Correct | Total | Success Rate |",
        "|----------|---------|-------|--------------|",
    ]

    for category in sorted(category_stats.keys()):
        stats = category_stats[category]
        rate = (stats["correct"] / stats["total"] * 100) if stats["total"] > 0 else 0
        lines.append(f"| {category} | {stats['correct']} | {stats['total']} | {rate:.1f}% |")

    return "\n".join(lines)


def generate_type_breakdown(results: InsertionBenchmarkResults) -> str:
    """Generate breakdown by inferred type.

    Args:
        results: Insertion benchmark results

    Returns:
        Formatted type breakdown as markdown
    """
    # Group results by inferred type
    type_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"correct": 0, "total": 0})

    for result in results.correct:
        if result.inferred_type is not None:
            type_stats[result.inferred_type]["correct"] += 1
            type_stats[result.inferred_type]["total"] += 1

    for result in results.type_mismatch:
        if result.inferred_type is not None:
            type_stats[result.inferred_type]["total"] += 1

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


def generate_failure_examples(results: InsertionBenchmarkResults, max_examples: int = 10) -> str:
    """Show examples of failures.

    Args:
        results: Insertion benchmark results
        max_examples: Maximum number of examples to show per category

    Returns:
        Formatted failure examples as markdown
    """
    lines = ["## Failure Examples", ""]

    # Type mismatches
    if results.type_mismatch:
        lines.append(f"### Type Mismatches (showing up to {max_examples}):")
        lines.append("")
        for result in results.type_mismatch[:max_examples]:
            lines.append(f"- **{result.case.category}**")
            lines.append(f"  - Variable: `{result.case.variable_name}`")
            lines.append(f"  - Inferred: `{result.inferred_type}`")
            lines.append(f"  - Expected: `{result.case.expected_types}`")
            lines.append(f"  - Reason: {result.reason}")
            lines.append("")

    # Insertion failures
    if results.insertion_failed:
        lines.append(f"### Insertion Failures (showing up to {max_examples}):")
        lines.append("")
        for result in results.insertion_failed[:max_examples]:
            lines.append(f"- **{result.case.category}**")
            lines.append(f"  - Variable: `{result.case.variable_name}`")
            lines.append(f"  - Inferred type: `{result.inferred_type}`")
            lines.append(f"  - Reason: {result.reason}")
            lines.append("")

    # Syntax errors
    if results.syntax_errors:
        lines.append(f"### Syntax Errors (showing up to {max_examples}):")
        lines.append("")
        for result in results.syntax_errors[:max_examples]:
            lines.append(f"- **{result.case.category}**")
            lines.append(f"  - Variable: `{result.case.variable_name}`")
            lines.append(f"  - Inferred type: `{result.inferred_type}`")
            lines.append(f"  - Error: {result.reason}")
            lines.append("")

    if len(lines) == 2:  # Only header
        return ""

    return "\n".join(lines)


def generate_report(results: InsertionBenchmarkResults) -> str:
    """Generate complete insertion benchmark report.

    Args:
        results: Insertion benchmark results

    Returns:
        Complete formatted report as markdown
    """
    sections = [
        "# Insertion Benchmark Report",
        "",
        generate_summary_section(results),
        "",
        generate_category_breakdown(results),
        "",
        generate_type_breakdown(results),
        "",
        generate_failure_examples(results),
    ]

    return "\n".join(sections)


def export_json(results: InsertionBenchmarkResults, output_path: Path) -> None:
    """Export detailed results to JSON file.

    Args:
        results: Insertion benchmark results
        output_path: Path to output JSON file
    """
    data = {
        "total": results.total,
        "summary": {
            "correct": len(results.correct),
            "type_mismatch": len(results.type_mismatch),
            "insertion_failed": len(results.insertion_failed),
            "inference_failed": len(results.inference_failed),
            "syntax_errors": len(results.syntax_errors),
            "annotation_missing": len(results.annotation_missing),
        },
        "results": [
            {
                "category": r.case.category,
                "file": str(r.case.file_path),
                "line": r.case.line_number,
                "variable": r.case.variable_name,
                "expected_types": r.case.expected_types,
                "status": r.status.value,
                "inferred_type": r.inferred_type,
                "type_matches": r.type_matches,
                "syntax_valid": r.syntax_valid,
                "insertion_success": r.insertion_success,
                "reason": r.reason,
            }
            for r in results.results
        ],
    }

    with output_path.open("w") as f:
        json.dump(data, f, indent=2)

    print(f"✓ Exported detailed results to {output_path}")


def export_failed_cases(results: InsertionBenchmarkResults, output_dir: Path) -> None:
    """Export failed cases to separate files for debugging.

    Args:
        results: Insertion benchmark results
        output_dir: Directory to write failure files
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Export type mismatches
    type_mismatch_file = output_dir / "type_mismatches.json"
    with type_mismatch_file.open("w") as f:
        json.dump(
            [
                {
                    "category": r.case.category,
                    "variable": r.case.variable_name,
                    "inferred": r.inferred_type,
                    "expected": r.case.expected_types,
                    "source": r.case.source_code,
                }
                for r in results.type_mismatch
            ],
            f,
            indent=2,
        )

    # Export insertion failures
    insertion_failed_file = output_dir / "insertion_failures.json"
    with insertion_failed_file.open("w") as f:
        json.dump(
            [
                {
                    "category": r.case.category,
                    "variable": r.case.variable_name,
                    "inferred_type": r.inferred_type,
                    "reason": r.reason,
                    "source": r.case.source_code,
                }
                for r in results.insertion_failed
            ],
            f,
            indent=2,
        )

    # Export syntax errors
    syntax_errors_file = output_dir / "syntax_errors.json"
    with syntax_errors_file.open("w") as f:
        json.dump(
            [
                {
                    "category": r.case.category,
                    "variable": r.case.variable_name,
                    "inferred_type": r.inferred_type,
                    "error": r.reason,
                    "original_source": r.case.source_code,
                    "modified_source": r.inserted_source,
                }
                for r in results.syntax_errors
            ],
            f,
            indent=2,
        )

    print(f"✓ Exported failure cases to {output_dir}/")
