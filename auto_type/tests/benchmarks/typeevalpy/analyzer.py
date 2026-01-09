"""Analyze unsupported patterns and create expansion roadmap."""

from collections import defaultdict
from dataclasses import dataclass

from tests.benchmarks.typeevalpy.runner import BenchmarkResults, InferenceResult


@dataclass
class PatternAnalysis:
    """Analysis of a specific unsupported pattern."""

    pattern_name: str  # "function_call", "binary_operation"
    count: int  # Number of occurrences
    examples: list[str]  # Up to 3 code examples
    coverage_gain: float  # Percentage gain if implemented
    effort_estimate: str  # "quick_win", "medium", "long_term"


@dataclass
class ExpansionRoadmap:
    """Prioritized roadmap for expanding inference capabilities."""

    quick_wins: list[PatternAnalysis]  # 1-2 hours each
    medium_effort: list[PatternAnalysis]  # 4-8 hours each
    long_term: list[PatternAnalysis]  # 1+ weeks each


def extract_code_examples(cases: list[InferenceResult], max_examples: int = 3) -> list[str]:
    """Extract code snippets showing the pattern."""
    examples = []

    for case in cases[:max_examples]:
        lines = case.case.source_code.split("\n")
        line_idx = case.case.line_number - 1  # Convert to 0-indexed

        if 0 <= line_idx < len(lines):
            code_line = lines[line_idx].strip()
            # Include variable name for context
            var_name = case.case.variable_name or "?"
            if "=" in code_line:
                rhs = code_line.split("=", 1)[1].strip()
                examples.append(f"{var_name} = {rhs}")
            else:
                examples.append(code_line)

    return examples


def estimate_implementation_effort(pattern_name: str) -> str:
    """Estimate effort based on pattern complexity."""

    quick_wins = {
        "unary_operation",  # Just extend pattern matching
        "binary_operation",  # Type arithmetic rules
    }

    medium_effort = {
        "function_call",  # Need builtin function database
        "subscript",  # Need element type tracking
        "attribute_access",  # Need method return type database
        "comparison",  # Returns bool
        "boolean_operation",  # Returns bool
    }

    # Everything else is long-term
    if pattern_name in quick_wins:
        return "quick_win"
    elif pattern_name in medium_effort:
        return "medium"
    else:
        return "long_term"


def analyze_unsupported_patterns(results: BenchmarkResults) -> list[PatternAnalysis]:
    """Group and analyze unsupported patterns."""

    # Group by failure reason
    pattern_groups: dict[str, list[InferenceResult]] = defaultdict(list)
    for result in results.unsupported:
        if result.reason is not None:
            pattern_groups[result.reason].append(result)

    # Create analysis for each pattern
    analyses = []
    for pattern_name, cases in pattern_groups.items():
        analyses.append(
            PatternAnalysis(
                pattern_name=pattern_name,
                count=len(cases),
                examples=extract_code_examples(cases, max_examples=3),
                coverage_gain=len(cases) / results.total * 100,
                effort_estimate=estimate_implementation_effort(pattern_name),
            )
        )

    # Sort by count descending (most common first)
    analyses.sort(key=lambda x: x.count, reverse=True)
    return analyses


def create_expansion_roadmap(analyses: list[PatternAnalysis]) -> ExpansionRoadmap:
    """Organize patterns into prioritized roadmap."""

    roadmap = ExpansionRoadmap(quick_wins=[], medium_effort=[], long_term=[])

    for analysis in analyses:
        if analysis.effort_estimate == "quick_win":
            roadmap.quick_wins.append(analysis)
        elif analysis.effort_estimate == "medium":
            roadmap.medium_effort.append(analysis)
        else:
            roadmap.long_term.append(analysis)

    return roadmap
