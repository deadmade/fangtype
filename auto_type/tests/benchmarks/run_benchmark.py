#!/usr/bin/env python3
"""Run TypeEvalPy benchmark on auto_type inference engine."""

import argparse
import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.benchmarks.typeevalpy.analyzer import (
    analyze_unsupported_patterns,
    create_expansion_roadmap,
)
from tests.benchmarks.typeevalpy.loader import load_benchmark
from tests.benchmarks.typeevalpy.reporter import export_json, generate_report
from tests.benchmarks.typeevalpy.runner import run_benchmark


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run TypeEvalPy benchmark on auto_type inference engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run full benchmark
  python scripts/run_benchmark.py

  # Filter to specific category
  python scripts/run_benchmark.py --category lists

  # Export detailed results
  python scripts/run_benchmark.py --output results.json

  # Custom benchmark location
  python scripts/run_benchmark.py --benchmark-dir /path/to/TypeEvalPy/micro-benchmark
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
    parser.add_argument("--output", type=Path, help="Export detailed results to JSON file")
    parser.add_argument(
        "--category",
        help="Filter to specific category (e.g., 'lists', 'assignments', 'builtins')",
    )
    parser.add_argument("--no-progress", action="store_true", help="Disable progress indicators")

    args = parser.parse_args()

    try:
        # Load benchmark
        print("=" * 60)
        print("TypeEvalPy Benchmark Runner")
        print("=" * 60)
        print()

        print("Loading benchmark...")
        cases = load_benchmark(args.benchmark_dir) if args.benchmark_dir else load_benchmark()

        print(f"✓ Loaded {len(cases)} annotations")

        # Filter by category if requested
        if args.category:
            cases = [c for c in cases if args.category in c.category]
            print(f"✓ Filtered to {len(cases)} cases in category '{args.category}'")
            if len(cases) == 0:
                print(f"⚠ No cases found matching category '{args.category}'")
                return 1

        print()

        # Run inference (uses DI container internally)
        print("Running inference...")
        results = run_benchmark(cases, show_progress=not args.no_progress)
        print()

        # Analyze patterns
        print("Analyzing patterns...")
        patterns = analyze_unsupported_patterns(results)
        roadmap = create_expansion_roadmap(patterns)
        print("✓ Analysis complete")
        print()

        # Generate report
        print("=" * 60)
        report = generate_report(results, roadmap)
        print(report)
        print("=" * 60)
        print()

        # Export if requested
        if args.output:
            export_json(results, args.output)

        return 0

    except FileNotFoundError as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"❌ Unexpected error: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
