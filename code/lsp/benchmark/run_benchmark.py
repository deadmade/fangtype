#!/usr/bin/env python3
"""Run TypeEvalPy benchmarks on fangtype."""

import argparse
import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from benchmark.lsp_client.client import set_mypy_gate
from benchmark.mypy_eval.insertion_runner import run_mypy_insertion_benchmark
from benchmark.mypy_eval.prepare import (
    build_toolchain_pins,
    get_prepared_dir,
    get_run_dir,
    is_working_tree_dirty,
    prepare_mypy_workspace,
    read_code_revision,
    read_git_revision,
)
from benchmark.mypy_eval.reporter import export_insertion_json, summarize_insertion
from benchmark.mypy_eval.reporter import export_json as export_mypy_json
from benchmark.mypy_eval.reporter import summarize as summarize_mypy
from benchmark.mypy_eval.runner import run_mypy_benchmark
from benchmark.typeevalpy.inference_runner import (
    enumerate_pairs,
    get_autogen_benchmark_dir,
    get_benchmark_dir,
    run_inference_benchmark,
    score_concept_lenient,
)
from benchmark.typeevalpy.insertion_runner import run_insertion_benchmark
from benchmark.typeevalpy.jedi_reference import run_jedi_benchmark
from benchmark.typeevalpy.reporter import export_json as export_inference_json
from benchmark.typeevalpy.reporter import summarize as summarize_inference


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

  # The gate-off twin of either insertion mode. Journals and labels separate the
  # two configurations, so the pair can be run back to back without colliding.
  python code/lsp/benchmark/run_benchmark.py --mode insertion --no-mypy-gate
  python code/lsp/benchmark/run_benchmark.py --mode mypy-insert --no-mypy-gate

  # Restore against a corpus with no annotations left anywhere, rather than one where
  # only the file under test is stripped. Same targets, same scorer, same stripped text.
  python code/lsp/benchmark/run_benchmark.py --mode mypy --cold-start
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
        "--no-mypy-gate",
        action="store_true",
        help=(
            "Disable the insert-path assignability gate, which ships enabled and is on here by "
            "default. Measures inference without the validation step that rejects a candidate "
            "against its real value, so insertion and parse figures from such a run do not "
            "describe the shipped pipeline."
        ),
    )
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
    parser.add_argument(
        "--cold-start",
        action="store_true",
        help=(
            "(mypy mode only) Resolve cross-module names against the fully stripped "
            "corpus instead of the original annotated checkout. The default run leaves "
            "every file but the one under test annotated, which is not the state a "
            "project adopting the tool is in; this measures the other end of that range."
        ),
    )
    parser.add_argument(
        "--force-prepare",
        action="store_true",
        help=(
            "(mypy modes only) Re-strip the mypy corpus even when the prepared tree is "
            "current. The tree is otherwise reused across runs, and is rebuilt "
            "automatically when the corpus revision or the removal engine changes."
        ),
    )
    return parser


def _reject_inference_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.reference is not None:
        parser.error("--reference is only valid with --mode inference")


def _reject_autogen(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.autogen:
        parser.error("--autogen is only valid with --mode inference or --mode insertion")


def _reject_force_prepare(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.force_prepare:
        parser.error("--force-prepare is only valid with --mode mypy or --mode mypy-insert")


def _reject_cold_start(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    """Refuse ``--cold-start`` outside the restore mode.

    Only the restore runner reads the cold tree. Accepting the flag elsewhere would run
    the ordinary configuration and then label the artefact as a cold-start measurement,
    which is worse than refusing it.
    """
    if args.cold_start:
        parser.error("--cold-start is only valid with --mode mypy")


def _validate_mode_specific_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.mode == "insertion":
        _reject_inference_args(args, parser)
        _reject_force_prepare(args, parser)
        _reject_cold_start(args, parser)
    elif args.mode == "mypy":
        _reject_inference_args(args, parser)
        _reject_autogen(args, parser)
    elif args.mode == "mypy-insert":
        _reject_inference_args(args, parser)
        _reject_autogen(args, parser)
        _reject_cold_start(args, parser)
    else:
        _reject_force_prepare(args, parser)
        _reject_cold_start(args, parser)


def _run_dir(args: argparse.Namespace) -> Path:
    """Resolve the per-configuration run directory that holds this run's resume journal."""
    return get_run_dir(args.engine, gate_enabled=not args.no_mypy_gate, cold_start=args.cold_start)


def _tool_name(args: argparse.Namespace, base: str) -> str:
    """Label a run by its configuration, so an artefact names the pipeline that produced it.

    A gate-off run measures a different pipeline than the shipped one. Deriving the label
    from the flag rather than from the ``--output`` filename is what stops the two being
    confused once the JSON is on disk.
    """
    label = base if not args.no_mypy_gate else f"{base}-nogate"
    return f"{label}-coldstart" if args.cold_start else label


def _typeevalpy_revision(args: argparse.Namespace) -> str:
    """Commit of the TypeEvalPy submodule this run scored.

    Resolved from the corpus directory actually used, so an ``--autogen`` run stamps
    the same submodule the micro-benchmark does rather than a hard-coded path. The
    mypy artefacts have carried ``mypy_revision`` all along; this is its counterpart,
    without which the TypeEvalPy revision the thesis cites rests on nothing.
    """
    return read_git_revision(args.benchmark_dir or get_benchmark_dir())


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
            tool_name=_tool_name(args, "fangtype"),
            show_progress=not args.no_progress,
        )
    except ValueError as exc:
        print(f"⚠ {exc}")
        return 1
    print()

    # Concept-lenient companion: credits non-insertable generator/code predictions in a
    # clearly-labeled secondary metric (never the headline).
    lenient_pairs = enumerate_pairs(args.benchmark_dir)
    lenient = score_concept_lenient(
        lenient_pairs, results.out_root, tool_name=_tool_name(args, "fangtype")
    )

    print("=" * 60)
    print(summarize_inference(results, lenient))
    print("=" * 60)
    print()

    if args.output:
        export_inference_json(
            results,
            args.output,
            lenient=lenient,
            engine=args.engine,
            gate_enabled=not args.no_mypy_gate,
            fangtype_revision=args.fangtype_revision,
            typeevalpy_revision=_typeevalpy_revision(args),
            toolchain=args.toolchain,
        )

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
        print(summarize_inference(reference, reference=results))
        print("=" * 60)
        print()

        if args.output:
            jedi_json = args.output.with_name(args.output.stem + "_jedi" + args.output.suffix)
            # No engine/gate_enabled here: this is TypeEvalPy's own bundled Jedi
            # runner, not a run of the Fangtype LSP pipeline, so neither concept
            # applies. fangtype_revision and toolchain still name the harness commit
            # and the interpreter/package versions that ran it.
            export_inference_json(
                reference,
                jedi_json,
                fangtype_revision=args.fangtype_revision,
                typeevalpy_revision=_typeevalpy_revision(args),
                toolchain=args.toolchain,
            )

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
            tool_name=_tool_name(args, "fangtype-insertion"),
            show_progress=not args.no_progress,
        )
    except ValueError as exc:
        print(f"⚠ {exc}")
        return 1
    print()

    print("=" * 60)
    print(summarize_inference(results, exact_label="Inserted w/ type (yield)"))
    print("=" * 60)
    print()

    if args.output:
        export_inference_json(
            results,
            args.output,
            engine=args.engine,
            gate_enabled=not args.no_mypy_gate,
            fangtype_revision=args.fangtype_revision,
            typeevalpy_revision=_typeevalpy_revision(args),
            toolchain=args.toolchain,
        )

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

    workspace = get_prepared_dir()

    print("Preparing mypy workspace...")
    preparation = prepare_mypy_workspace(workspace=workspace, force=args.force_prepare)
    print(
        ("✓ Reused " if preparation.reused else "✓ Prepared ")
        + f"{preparation.total_python_files} Python files "
        f"({preparation.typed_file_count} typed, "
        f"{preparation.untyped_file_count} untyped, "
        f"{preparation.error_file_count} errors)"
    )
    print(f"✓ Workspace: {preparation.workspace}")
    print()

    if insert:
        return _run_mypy_insertion(args, workspace)

    print("Running mypy restoration benchmark...")
    journal_path = _run_dir(args) / "journal.jsonl"
    print(f"Journal: {journal_path} (per-file results appended live; delete to start fresh)")
    results = run_mypy_benchmark(
        workspace,
        journal_path=journal_path,
        engine=args.engine,
        cold_start=args.cold_start,
    )
    print()

    print("=" * 60)
    print(summarize_mypy(results))
    print("=" * 60)
    print()

    if args.output:
        export_mypy_json(
            results,
            args.output,
            engine=args.engine,
            gate_enabled=not args.no_mypy_gate,
            resolution_context="cold" if args.cold_start else "annotated",
            fangtype_revision=args.fangtype_revision,
            toolchain=args.toolchain,
        )

    return 0


def _run_mypy_insertion(args: argparse.Namespace, workspace: Path) -> int:
    print("Running mypy insertion benchmark...")
    print("(insertion yield: infer types → insert annotations → validate the modified files)")
    journal_path = _run_dir(args) / "journal_insertion.jsonl"
    print(f"Journal: {journal_path} (per-file results appended live; delete to start fresh)")
    results = run_mypy_insertion_benchmark(
        workspace,
        journal_path=journal_path,
        engine=args.engine,
    )
    print()

    print("=" * 60)
    print(summarize_insertion(results))
    print("=" * 60)
    print()

    if args.output:
        export_insertion_json(
            results,
            args.output,
            engine=args.engine,
            gate_enabled=not args.no_mypy_gate,
            fangtype_revision=args.fangtype_revision,
            toolchain=args.toolchain,
        )

    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    _validate_mode_specific_args(args, parser)

    args.benchmark_dir = get_autogen_benchmark_dir() if args.autogen else None
    # code/lsp only, not the whole repository. The thesis lives beside the server here,
    # so committing a chapter between two invocations of a seven-command sweep would
    # otherwise stamp a different revision on each artefact and make them disagree over
    # a commit that changed no measured line. Same reasoning as the dirty check below.
    code_lsp_root = Path(__file__).resolve().parents[1]
    # Stamped onto every exported artefact, so a pin claimed in the thesis can be
    # checked against the JSON rather than taken on the operator's word.
    args.fangtype_revision = read_code_revision(code_lsp_root)
    dirty = is_working_tree_dirty(code_lsp_root)
    args.toolchain = {
        **build_toolchain_pins(),
        "fangtype_dirty": "unknown" if dirty is None else dirty,
    }

    # Pushed to every server the run spawns, so it has to be set before the first bridge.
    set_mypy_gate(not args.no_mypy_gate)

    # All three modes drive everything through the LSP server (spawned by the
    # runner via ClientBridge / resolve_workflow_and_engine + FANGTYPE_ENGINE), so
    # none of them build an in-process container.
    print(f"⚙ Inference engine (LSP server): {args.engine}")
    print(f"⚙ Insert-path assignability gate: {'off' if args.no_mypy_gate else 'on (shipped)'}")

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
