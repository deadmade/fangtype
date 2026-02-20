"""Insertion benchmark package for testing InsertionEngine."""

from benchmark.insertion.loader import load_insertable_cases
from benchmark.insertion.reporter import export_json, generate_report
from benchmark.insertion.runner import run_insertion_benchmark
from benchmark.insertion.validator import validate_insertion_result, validate_syntax

__all__ = [
    "export_json",
    "generate_report",
    "load_insertable_cases",
    "run_insertion_benchmark",
    "validate_insertion_result",
    "validate_syntax",
]
