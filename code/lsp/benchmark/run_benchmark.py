#!/usr/bin/env python3
"""Run TypeEvalPy benchmarks on fangtype."""

import argparse
import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from benchmark.lsp_client.pool import resolve_workers
from benchmark.mypy_eval.insertion_runner import run_mypy_insertion_benchmark
from benchmark.mypy_eval.prepare import (
    get_default_workspace,
    prepare_mypy_workspace,
)
from benchmark.mypy_eval.reporter import export_insertion_json, generate_insertion_report
from benchmark.mypy_eval.reporter import export_json as export_mypy_json
from benchmark.mypy_eval.reporter import generate_report as generate_mypy_report
from benchmark.mypy_eval.runner import run_mypy_benchmark
from benchmark.typeevalpy.inference_runner import (
    enumerate_pairs,
    get_autogen_benchmark_dir,
    run_inference_benchmark,
    score_concept_lenient,
)
from benchmark.typeevalpy.insertion_runner import run_insertion_benchmark
from benchmark.typeevalpy.jedi_reference import run_jedi_benchmark
from benchmark.typeevalpy.reporter import export_json as export_inference_json
from benchmark.typeevalpy.reporter import generate_comparison, generate_lenient_companion
from benchmark.typeevalpy.reporter import generate_report as generate_inference_report


def build_parser() -> argparse.ArgumentParser:
    """Build command line parser for benchmark CLI."""
    parser = argparse.ArgumentParser(
        description="Run fangtype benchmarks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run inference benchmark (default mode)
  python code/lsp/benchmark/run_benchmark.py

  # Run insertion benchmark
  python code/lsp/benchmark/run_benchmark.py --mode insertion

  # Run against the TypeEvalPy Autogen corpus (~5453 cases) instead of micro-benchmark
  python code/lsp/benchmark/run_benchmark.py --autogen

  # Export detailed results
  python code/lsp/benchmark/run_benchmark.py --output results.json

  # Prepare and run the mypy restoration evaluation
  python code/lsp/benchmark/run_benchmark.py --mode mypy

  # Run the mypy insertion evaluation
  python code/lsp/benchmark/run_benchmark.py --mode mypy-insert
""",
    )

    parser.add_argument(
        "--mode",
        choices=["inference", "insertion", "mypy", "mypy-insert"],
        default="inference",
        help="Benchmark mode to run (default: inference)",
    )
    parser.add_argument(
        "--autogen",
        action="store_true",
        help=(
            "Use the TypeEvalPy Autogen corpus "
            "(data/TypeEvalPy/autogen_typeevalpy_benchmark, ~5453 cases) instead of the "
            "default micro-benchmark. Inference/insertion modes only."
        ),
    )
    parser.add_argument("--output", type=Path, help="Export detailed results to JSON file")
    parser.add_argument("--no-progress", action="store_true", help="Disable progress indicators")
    parser.add_argument(
        "--engine",
        choices=["jedi"],
        default="jedi",
        help="Inference engine backend to benchmark (default: jedi)",
    )
    parser.add_argument(
        "--reference",
        choices=["jedi"],
        default=None,
        help="(inference mode only) Also run and compare against a reference tool",
    )
    return parser


def _reject_inference_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.reference is not None:
        parser.error("--reference is only valid with --mode inference")


def _reject_autogen(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.autogen:
        parser.error("--autogen is only valid with --mode inference or --mode insertion")


def _validate_mode_specific_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.mode == "insertion":
        _reject_inference_args(args, parser)
    elif args.mode in ("mypy", "mypy-insert"):
        _reject_inference_args(args, parser)
        _reject_autogen(args, parser)


def _run_inference_mode(args: argparse.Namespace) -> int:
    print("=" * 60)
    print("TypeEvalPy Benchmark Runner (Inference Mode)")
    print("=" * 60)
    print()

    print("Running inference over the LSP server...")
    try:
        results = run_inference_benchmark(
            engine=args.engine,
            benchmark_dir=args.benchmark_dir,
            show_progress=not args.no_progress,
            workers=args.workers,
        )
    except ValueError as exc:
        print(f"⚠ {exc}")
        return 1
    print()

    print("=" * 60)
    report = generate_inference_report(results)
    print(report)
    print("=" * 60)
    print()

    # Concept-lenient companion: credits non-insertable generator/code predictions in a
    # clearly-labeled secondary metric (never the headline). See generate_lenient_companion.
    lenient_pairs = enumerate_pairs(args.benchmark_dir)
    lenient = score_concept_lenient(lenient_pairs, results.out_root, tool_name="fangtype")
    print(generate_lenient_companion(results, lenient))
    print("=" * 60)
    print()

    if args.output:
        export_inference_json(results, args.output)

    if args.reference == "jedi":
        print("Running local Jedi reference benchmark...")
        try:
            reference = run_jedi_benchmark(
                benchmark_dir=args.benchmark_dir,
                show_progress=not args.no_progress,
            )
        except ValueError as exc:
            print(f"⚠ {exc}")
            return 1
        print()

        print("=" * 60)
        print(generate_inference_report(reference))
        print("=" * 60)
        print()

        print(generate_comparison(results, reference))
        print()

    return 0


def _run_insertion_mode(args: argparse.Namespace) -> int:
    print("=" * 60)
    print("TypeEvalPy Benchmark Runner (Insertion Mode)")
    print("=" * 60)
    print()

    print("Running insertion over the LSP server...")
    print("(insertion yield: of what inference produced, how much the server inserts)")
    try:
        results = run_insertion_benchmark(
            engine=args.engine,
            benchmark_dir=args.benchmark_dir,
            show_progress=not args.no_progress,
            workers=args.workers,
        )
    except ValueError as exc:
        print(f"⚠ {exc}")
        return 1
    print()

    print("=" * 60)
    report = generate_inference_report(
        results,
        title="TypeEvalPy Insertion Benchmark -- insertion yield",
        subtitle=(
            "(of the types inference produced, how many the server inserted with the "
            "correct type -- not scored against TypeEvalPy ground truth)"
        ),
        exact_label="Inserted w/ correct type (yield)",
        partial_label="Inserted (any type)",
        sound_label="Files fully inserted",
        complete_label="Files with valid output",
    )
    print(report)
    print("=" * 60)
    print()

    if args.output:
        export_inference_json(results, args.output)

    return 0


def _run_mypy_mode(args: argparse.Namespace) -> int:
    insert = args.mode == "mypy-insert"
    print("=" * 60)
    if insert:
        print("Mypy Insertion Benchmark Runner")
    else:
        print("Mypy Restoration Benchmark Runner")
    print("=" * 60)
    print()

    workspace = get_default_workspace()

    print("Preparing mypy workspace...")
    preparation = prepare_mypy_workspace(workspace=workspace)
    print(
        "✓ Prepared "
        f"{preparation.total_python_files} Python files "
        f"({preparation.typed_file_count} typed, "
        f"{preparation.untyped_file_count} untyped, "
        f"{preparation.error_file_count} errors)"
    )
    print(f"✓ Workspace: {preparation.workspace}")
    print()

    if insert:
        return _run_mypy_insertion(args, workspace)

    print("Running mypy restoration benchmark...")
    journal_path = workspace / f"journal_{args.engine}.jsonl"
    print(f"Journal: {journal_path} (per-file results appended live; delete to start fresh)")
    results = run_mypy_benchmark(
        workspace, journal_path=journal_path, engine=args.engine, workers=args.workers
    )
    print()

    print("=" * 60)
    report = generate_mypy_report(results)
    print(report)
    print("=" * 60)
    print()

    if args.output:
        export_mypy_json(results, args.output)

    return 0


def _run_mypy_insertion(args: argparse.Namespace, workspace: Path) -> int:
    print("Running mypy insertion benchmark...")
    print("(insertion yield: infer types → insert annotations → validate the modified files)")
    journal_path = workspace / f"journal_insertion_{args.engine}.jsonl"
    print(f"Journal: {journal_path} (per-file results appended live; delete to start fresh)")
    results = run_mypy_insertion_benchmark(
        workspace,
        journal_path=journal_path,
        engine=args.engine,
        workers=args.workers,
    )
    print()

    print("=" * 60)
    print(generate_insertion_report(results))
    print("=" * 60)
    print()

    if args.output:
        export_insertion_json(results, args.output)

    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    _validate_mode_specific_args(args, parser)

    args.benchmark_dir = get_autogen_benchmark_dir() if args.autogen else None
    args.workers = resolve_workers(None)

    # All three modes drive everything through the LSP server (spawned by the
    # runner via ClientBridge / resolve_workflow_and_engine + FANGTYPE_ENGINE), so
    # none of them build an in-process container.
    print(f"⚙ Inference engine (LSP server): {args.engine}")
    print(f"⚙ Parallel workers (LSP subprocesses): {args.workers}")

    try:
        if args.mode == "insertion":
            return _run_insertion_mode(args)
        if args.mode in ("mypy", "mypy-insert"):
            return _run_mypy_mode(args)
        return _run_inference_mode(args)
    except FileNotFoundError as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n⚠ Interrupted by user", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"❌ Unexpected error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
