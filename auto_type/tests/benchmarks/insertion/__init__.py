"""Insertion benchmark package for testing InsertionEngine."""

from tests.benchmarks.insertion.loader import load_insertable_cases
from tests.benchmarks.insertion.reporter import export_json, generate_report
from tests.benchmarks.insertion.runner import run_insertion_benchmark
from tests.benchmarks.insertion.validator import validate_insertion_result, validate_syntax

__all__ = [
    "export_json",
    "generate_report",
    "load_insertable_cases",
    "run_insertion_benchmark",
    "validate_insertion_result",
    "validate_syntax",
]
