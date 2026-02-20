#!/usr/bin/env python3
"""Run TypeEvalPy benchmarks on auto_type."""

import argparse
import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from benchmark.insertion.loader import load_insertable_cases
from benchmark.insertion.reporter import (
    export_failed_cases,
)
from benchmark.insertion.reporter import (
    export_json as export_insertion_json,
)
from benchmark.insertion.reporter import (
    generate_report as generate_insertion_report,
)
from benchmark.insertion.runner import run_insertion_benchmark
from benchmark.typeevalpy.loader import load_benchmark
from benchmark.typeevalpy.reporter import (
    export_json as export_inference_json,
)
from benchmark.typeevalpy.reporter import (
    generate_report as generate_inference_report,
)
from benchmark.typeevalpy.runner import run_benchmark as run_inference_benchmark


def build_parser() -> argparse.ArgumentParser:
    """Build command line parser for benchmark CLI."""
    parser = argparse.ArgumentParser(
        description="Run TypeEvalPy benchmarks on auto_type",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run inference benchmark (default mode)
  python auto_type/benchmark/run_benchmark.py

  # Run insertion benchmark
  python auto_type/benchmark/run_benchmark.py --mode insertion

  # Filter to specific category
  python auto_type/benchmark/run_benchmark.py --mode insertion --category lists

  # Export detailed results
  python auto_type/benchmark/run_benchmark.py --output results.json

  # Export insertion failures for debugging
  python auto_type/benchmark/run_benchmark.py --mode insertion --export-failures failures/

  # Limit insertion cases (for testing)
  python auto_type/benchmark/run_benchmark.py --mode insertion --max-cases 100
""",
    )

    parser.add_argument(
        "--mode",
        choices=["inference", "insertion"],
        default="inference",
        help="Benchmark mode to run (default: inference)",
    )
    parser.add_argument(
        "--benchmark-dir",
        type=Path,
        default=None,
        help=(
            "Path to TypeEvalPy micro-benchmark directory "
            "(default: auto_type/benchmarks/data/TypeEvalPy/micro-benchmark)"
        ),
    )
    parser.add_argument("--output", type=Path, help="Export detailed results to JSON file")
    parser.add_argument(
        "--category",
        help="Filter to specific category (e.g., 'lists', 'assignments', 'builtins')",
    )
    parser.add_argument("--no-progress", action="store_true", help="Disable progress indicators")

    # Insertion-only options.
    parser.add_argument(
        "--export-failures",
        type=Path,
        help="(insertion mode only) Export failed cases to directory for debugging",
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        help="(insertion mode only) Limit number of cases to process",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="(insertion mode only) Show traceback on unexpected errors",
    )
    return parser


def _filter_cases_by_category(
    cases: list[object], category: str | None
) -> tuple[list[object], bool]:
    if category is None:
        return cases, True

    filtered = [case for case in cases if category in case.category]
    print(f"✓ Filtered to {len(filtered)} cases in category '{category}'")
    if len(filtered) == 0:
        print(f"⚠ No cases found matching category '{category}'")
        return filtered, False
    return filtered, True


def _validate_mode_specific_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.mode == "inference":
        if args.export_failures is not None:
            parser.error("--export-failures is only valid with --mode insertion")
        if args.max_cases is not None:
            parser.error("--max-cases is only valid with --mode insertion")
        if args.verbose:
            parser.error("--verbose is only valid with --mode insertion")


def _run_inference_mode(args: argparse.Namespace) -> int:
    print("=" * 60)
    print("TypeEvalPy Benchmark Runner (Inference Mode)")
    print("=" * 60)
    print()

    print("Loading benchmark...")
    cases = load_benchmark(args.benchmark_dir) if args.benchmark_dir else load_benchmark()
    print(f"✓ Loaded {len(cases)} annotations")

    filtered_cases, ok = _filter_cases_by_category(cases, args.category)
    if not ok:
        return 1

    print()
    print("Running inference...")
    results = run_inference_benchmark(filtered_cases, show_progress=not args.no_progress)
    print()

    print("=" * 60)
    report = generate_inference_report(results)
    print(report)
    print("=" * 60)
    print()

    if args.output:
        export_inference_json(results, args.output)

    return 0


def _run_insertion_mode(args: argparse.Namespace) -> int:
    print("=" * 60)
    print("TypeEvalPy Benchmark Runner (Insertion Mode)")
    print("=" * 60)
    print()

    print("Loading benchmark cases...")
    cases = load_insertable_cases(args.benchmark_dir)
    print(f"✓ Loaded {len(cases)} benchmark cases (all types, no filtering)")

    filtered_cases, ok = _filter_cases_by_category(cases, args.category)
    if not ok:
        return 1

    if args.max_cases and args.max_cases < len(filtered_cases):
        filtered_cases = filtered_cases[: args.max_cases]
        print(f"✓ Limited to {args.max_cases} cases")

    print()
    print("Running insertion benchmark...")
    print("(This tests: Inference -> Insertion -> Validation)")
    print()
    results = run_insertion_benchmark(
        filtered_cases,
        show_progress=not args.no_progress,
    )
    print()

    print("=" * 60)
    report = generate_insertion_report(results)
    print(report)
    print("=" * 60)
    print()

    if args.output:
        export_insertion_json(results, args.output)

    if args.export_failures:
        export_failed_cases(results, args.export_failures)

    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    _validate_mode_specific_args(args, parser)

    try:
        if args.mode == "insertion":
            return _run_insertion_mode(args)
        return _run_inference_mode(args)
    except FileNotFoundError as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n⚠ Interrupted by user", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"❌ Unexpected error: {e}", file=sys.stderr)
        if args.mode == "insertion" and args.verbose:
            import traceback

            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
