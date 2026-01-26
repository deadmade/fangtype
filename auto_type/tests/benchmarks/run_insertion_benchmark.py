#!/usr/bin/env python3
"""Run TypeEvalPy insertion benchmark on auto_type.

This benchmark tests the complete pipeline on ALL TypeEvalPy cases:
1. JediInferenceEngine infers types
2. InsertionEngine inserts type annotations
3. Validator checks correctness (syntax + semantic)

Note: No filtering is applied - all ~845 TypeEvalPy cases are processed,
including functions, parameters, complex variables, and already-annotated code.
Many will result in INSERTION_FAILED since InsertionEngine only supports
simple variable annotations. This is expected.
"""

import argparse
import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.benchmarks.insertion.loader import load_insertable_cases
from tests.benchmarks.insertion.reporter import export_failed_cases, export_json, generate_report
from tests.benchmarks.insertion.runner import run_insertion_benchmark


def main() -> int:
    """Main entry point for insertion benchmark CLI.

    Returns:
        Exit code (0 = success, 1 = error)
    """
    parser = argparse.ArgumentParser(
        description="Run TypeEvalPy insertion benchmark on auto_type (all cases, no filtering)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run full insertion benchmark (all ~845 cases)
  python run_insertion_benchmark.py

  # Filter to specific category
  python run_insertion_benchmark.py --category lists

  # Export detailed results
  python run_insertion_benchmark.py --output results.json

  # Export failure cases for debugging
  python run_insertion_benchmark.py --export-failures failures/

  # Custom benchmark location
  python run_insertion_benchmark.py --benchmark-dir /path/to/TypeEvalPy/micro-benchmark

  # Limit number of cases (for testing)
  python run_insertion_benchmark.py --max-cases 100

Note: All TypeEvalPy cases are processed (no filtering). Many cases will fail
with INSERTION_FAILED or ANNOTATION_MISSING since InsertionEngine only supports
simple variable annotations. This helps identify system limitations.
""",
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
    parser.add_argument(
        "--output",
        type=Path,
        help="Export detailed results to JSON file",
    )
    parser.add_argument(
        "--export-failures",
        type=Path,
        help="Export failed cases to directory for debugging",
    )
    parser.add_argument(
        "--category",
        help="Filter to specific category (e.g., 'lists', 'assignments', 'builtins')",
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        help="Limit number of cases to process (for testing)",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable progress indicators",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed logging",
    )

    args = parser.parse_args()

    try:
        # Print header
        print("=" * 60)
        print("TypeEvalPy Insertion Benchmark")
        print("=" * 60)
        print()

        # Load ALL benchmark cases (no filtering)
        print("Loading benchmark cases...")
        cases = load_insertable_cases(args.benchmark_dir)
        print(f"✓ Loaded {len(cases)} benchmark cases (all types, no filtering)")

        # Filter by category if requested
        if args.category:
            cases = [c for c in cases if args.category in c.category]
            print(f"✓ Filtered to {len(cases)} cases in category '{args.category}'")
            if len(cases) == 0:
                print(f"⚠ No cases found matching category '{args.category}'")
                return 1

        # Limit cases if requested
        if args.max_cases and args.max_cases < len(cases):
            cases = cases[: args.max_cases]
            print(f"✓ Limited to {args.max_cases} cases")

        print()

        # Run benchmark (uses DI container internally)
        print("Running insertion benchmark...")
        print("(This tests: Inference → Insertion → Validation)")
        print()
        results = run_insertion_benchmark(
            cases,
            show_progress=not args.no_progress,
        )
        print()

        # Generate report
        print("=" * 60)
        report = generate_report(results)
        print(report)
        print("=" * 60)
        print()

        # Export results if requested
        if args.output:
            export_json(results, args.output)

        # Export failures if requested
        if args.export_failures:
            export_failed_cases(results, args.export_failures)

        return 0

    except FileNotFoundError as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n⚠ Interrupted by user", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"❌ Unexpected error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback

            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
