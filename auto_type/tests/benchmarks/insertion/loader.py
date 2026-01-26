"""Load TypeEvalPy benchmark cases for insertion testing.

This module loads ALL TypeEvalPy benchmark cases without filtering.
Previously filtered to simple variable assignments only - now includes all
annotation types (functions, parameters, complex variables) to benchmark
against the complete dataset.
"""

from pathlib import Path

from tests.benchmarks.typeevalpy.loader import BenchmarkCase, load_benchmark


def load_insertable_cases(benchmark_dir: Path | None = None) -> list[BenchmarkCase]:
    """Load ALL benchmark cases (no filtering).

    Note: Previously filtered to insertable cases only (simple variables,
    not already annotated). Now returns all cases to benchmark against the
    complete TypeEvalPy dataset (~845 cases).

    Many cases will result in INSERTION_FAILED or ANNOTATION_MISSING status
    since InsertionEngine only supports simple variable annotations. This is
    expected and helps identify system limitations.

    Args:
        benchmark_dir: Optional path to TypeEvalPy micro-benchmark directory.
                      If None, uses default location.

    Returns:
        List of ALL BenchmarkCase objects from TypeEvalPy

    Raises:
        FileNotFoundError: If benchmark directory doesn't exist
    """
    # Load and return all benchmark cases - no filtering
    return load_benchmark(benchmark_dir)
