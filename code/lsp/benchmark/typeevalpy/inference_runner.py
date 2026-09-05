"""Drive the fangtype LSP server over the TypeEvalPy micro-benchmark and score the
resulting prediction facts with the upstream submodule scorer.
"""

from __future__ import annotations

import json
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from benchmark.lsp_client.factory import ClientBridge, map_over_bridge
from benchmark.typeevalpy import official
from benchmark.typeevalpy.fact_emitter import emit_facts

TYPE_CATEGORIES: tuple[str, ...] = tuple(official.categorize_facts([]).keys())

_PROGRESS_EVERY = 25


@dataclass
class InferenceScore:
    """Aggregated official TypeEvalPy recall scoring across a set of files."""

    tool_name: str
    file_count: int
    num_all: int  # total GT facts scored (recall denominator)
    num_caught_exact: int
    num_caught_partial: int
    per_category: dict[str, dict[str, int]]  # {cat: {"num_all", "num_caught_exact"}}
    sound_count: int  # files where equal_sound == 1 (no false negatives)
    complete_count: int  # files where equal_complete == 1 (no false positives)
    out_root: Path
    # Exact matches bucketed by python_features/<folder>/, then by FR/FP/LV.
    # Same shape as TypeEvalPy paper Table 1. Empty when no files were scored.
    per_folder: dict[str, dict[str, dict[str, int]]] = field(default_factory=dict)

    @property
    def exact_pct(self) -> float:
        """Exact-match recall percentage (0 when there are no GT facts)."""
        return (self.num_caught_exact / self.num_all * 100) if self.num_all else 0.0


def _relative_to_features(path: Path) -> Path:
    """Return ``path`` relative to its enclosing ``python_features`` directory."""
    parts = path.parts
    idx = parts.index("python_features")
    return Path(*parts[idx + 1 :])


def _result_path(py_path: Path, out_root: Path) -> Path:
    rel = _relative_to_features(py_path)
    return out_root / rel.parent / f"{py_path.stem}_result.json"


def get_benchmark_dir() -> Path:
    """Locate the TypeEvalPy micro-benchmark corpus, ensuring it exists."""
    benchmark_dir = Path(__file__).parent.parent / "data" / "TypeEvalPy" / "micro-benchmark"

    if not benchmark_dir.exists():
        raise FileNotFoundError(
            f"TypeEvalPy benchmark not found at {benchmark_dir}\n\n"
            "Please clone it:\n"
            "  cd code/lsp/benchmark/data\n"
            "  git clone https://github.com/secure-software-engineering/TypeEvalPy.git"
        )

    return benchmark_dir


def get_autogen_benchmark_dir() -> Path:
    """Locate the TypeEvalPy Autogen corpus (ships inside the TypeEvalPy submodule)."""
    benchmark_dir = (
        Path(__file__).parent.parent / "data" / "TypeEvalPy" / "autogen_typeevalpy_benchmark"
    )

    if not benchmark_dir.exists():
        raise FileNotFoundError(
            f"TypeEvalPy Autogen corpus not found at {benchmark_dir}\n\n"
            "It ships inside the TypeEvalPy submodule. Ensure it is checked out:\n"
            "  cd code/lsp/benchmark/data\n"
            "  git clone https://github.com/secure-software-engineering/TypeEvalPy.git"
        )

    return benchmark_dir


def enumerate_pairs(benchmark_dir: Path | None = None) -> list[tuple[Path, Path]]:
    """Find (source.py, source_gt.json) pairs under ``python_features``.

    Args:
        benchmark_dir: the micro-benchmark root (default: ``get_benchmark_dir()``).

    Returns:
        A sorted list of ``(source_path, gt_path)`` tuples. Ground-truth files with
        no matching source file (``*_gt.json`` -> same-named ``*.py``) are skipped.
    """
    if benchmark_dir is None:
        benchmark_dir = get_benchmark_dir()
    features_dir = benchmark_dir / "python_features"

    pairs: list[tuple[Path, Path]] = []
    for gt_path in features_dir.rglob("*_gt.json"):
        source_path = gt_path.with_name(gt_path.name.replace("_gt.json", ".py"))
        if not source_path.exists():
            continue
        pairs.append((source_path, gt_path))

    return sorted(pairs)


def run_predictions(
    pairs: list[tuple[Path, Path]],
    engine: str,
    out_root: Path,
    show_progress: bool = True,
) -> None:
    """Drive the LSP server once per source file, writing one ``*_result.json`` each.

    A result file is always written, even when a file yields no facts (empty list) --
    ``score`` requires every pair to have a corresponding result on disk. Every file
    goes through one server process, in input order, which is the configuration the tool
    actually ships in. That says nothing about the *content* of a given result -- two
    runs have been measured to infer a different candidate set on some files (see
    ``sec:eval-threats`` in the thesis), and per-process inference state (Jedi's own
    caching, the server's document cache) is the
    leading unconfirmed candidate for why.
    """
    if not pairs:
        return

    total = len(pairs)

    def predict(bridge: ClientBridge, pair: tuple[Path, Path], _index: int) -> None:
        py_path, _gt_path = pair
        source = py_path.read_text()
        uri = py_path.resolve().as_uri()
        hints, name_facts = bridge.collect_sync(uri, source, did_open=False)
        facts = emit_facts(source, hints, name_facts, filename=py_path.name)
        facts = official.sort_facts(facts)

        result_path = _result_path(py_path, out_root)
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(facts, indent=2))

    done = 0

    def report(_index: int, _pair: tuple[Path, Path], _result: None) -> None:
        nonlocal done
        done += 1
        if show_progress and done % _PROGRESS_EVERY == 0:
            print(f"Progress: [{done}/{total}] ({done / total * 100:.1f}%)")

    map_over_bridge(
        pairs,
        make_bridge=lambda: ClientBridge(engine=engine),
        fn=predict,
        on_done=report,
    )

    if show_progress:
        print(f"Progress: [{total}/{total}] (100.0%)")


def score(pairs: list[tuple[Path, Path]], out_root: Path, tool_name: str) -> InferenceScore:
    """Score every (result, ground-truth) pair with the upstream submodule scorer."""
    num_all = 0
    num_caught_exact = 0
    num_caught_partial = 0
    per_category: dict[str, dict[str, int]] = {
        cat: {"num_all": 0, "num_caught_exact": 0} for cat in TYPE_CATEGORIES
    }
    per_folder: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: {cat: {"num_all": 0, "num_caught_exact": 0} for cat in TYPE_CATEGORIES}
    )
    sound_count = 0
    complete_count = 0

    for py_path, gt_path in pairs:
        result_path = _result_path(py_path, out_root)
        if not result_path.exists():
            msg = (
                f"Missing prediction result for {py_path} at {result_path}; "
                "run_predictions must be called before score()."
            )
            raise FileNotFoundError(msg)

        results, results_cat, results_only_cat = official.measure_recall(
            str(result_path), str(gt_path), tool_name
        )
        num_all += results["num_all"]
        num_caught_exact += results["num_caught_exact"]
        num_caught_partial += results["num_caught_partial"]

        for cat in TYPE_CATEGORIES:
            per_category[cat]["num_caught_exact"] += results_only_cat[cat]["num_caught_exact"]
            per_category[cat]["num_all"] += results_cat[1][cat]["num_all"]

        folder = _relative_to_features(py_path).parts[0]
        bucket = per_folder[folder]
        for cat in TYPE_CATEGORIES:
            bucket[cat]["num_caught_exact"] += results_only_cat[cat]["num_caught_exact"]
            bucket[cat]["num_all"] += results_cat[1][cat]["num_all"]

        sound_count += official.equal_sound(str(result_path), str(gt_path))
        complete_count += official.equal_complete(str(result_path), str(gt_path))

    return InferenceScore(
        tool_name=tool_name,
        file_count=len(pairs),
        num_all=num_all,
        num_caught_exact=num_caught_exact,
        num_caught_partial=num_caught_partial,
        per_category=per_category,
        sound_count=sound_count,
        complete_count=complete_count,
        out_root=out_root,
        per_folder=dict(per_folder),
    )


# Concept-lenient companion scoring. The honest LSP emits Jedi's real runtime `types`
# names; TypeEvalPy's ground truth uses the bare short spellings for these generator/code
# objects. These aliases credit the concept in a SEPARATE, clearly-labeled companion metric
# -- never the headline -- because `generator`/`code` are not valid, insertable annotations.
# (`Generator[...]` needs no alias: the vendored scorer bracket-strips it to `generator`.)
_CONCEPT_LENIENT_ALIASES: dict[str, str] = {
    "GeneratorType": "generator",
    "CodeType": "code",
}


def write_lenient_results(
    pairs: list[tuple[Path, Path]], out_root: Path, lenient_root: Path
) -> None:
    """Copy honest ``*_result.json`` files into ``lenient_root``, aliasing predicted types.

    Reads each prediction written under ``out_root`` and re-emits it under ``lenient_root``
    with every ``"type"`` entry mapped through ``_CONCEPT_LENIENT_ALIASES``. The honest files
    under ``out_root`` are left untouched. Missing prediction files are skipped (``score``
    raises on them later if required).
    """
    for py_path, _gt_path in pairs:
        src = _result_path(py_path, out_root)
        if not src.exists():
            continue
        facts = json.loads(src.read_text())
        for fact in facts:
            fact["type"] = [_CONCEPT_LENIENT_ALIASES.get(t, t) for t in fact.get("type", [])]
        dst = _result_path(py_path, lenient_root)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(json.dumps(facts, indent=2))


def score_concept_lenient(
    pairs: list[tuple[Path, Path]], out_root: Path, tool_name: str
) -> InferenceScore:
    """Score the concept-lenient companion metric over honest predictions in ``out_root``.

    Writes aliased copies to an ``out_root/_lenient`` sibling tree and scores those with the
    same official scorer. This credits non-insertable ``generator``/``code`` predictions and
    is reported ALONGSIDE (never instead of) the strict/insertable headline score.
    """
    lenient_root = out_root / "_lenient"
    write_lenient_results(pairs, out_root, lenient_root)
    return score(pairs, lenient_root, tool_name)


def run_inference_benchmark(
    engine: str = "jedi",
    *,
    benchmark_dir: Path | None = None,
    tool_name: str = "fangtype",
    out_root: Path | None = None,
    show_progress: bool = True,
) -> InferenceScore:
    """Run predictions over the LSP server and score them, end to end.

    Args:
        engine: inference engine backend to run the LSP server with.
        benchmark_dir: micro-benchmark root (default: ``get_benchmark_dir()``).
        tool_name: label passed through to the scorer / report.
        out_root: where to write ``*_result.json`` files (default: a fresh
            ``tempfile.mkdtemp`` directory, reported via ``InferenceScore.out_root``
            so results can be inspected afterwards).
        show_progress: print progress lines while predictions run.
    """
    pairs = enumerate_pairs(benchmark_dir)
    if not pairs:
        msg = "No benchmark files found"
        raise ValueError(msg)

    if out_root is None:
        out_root = Path(tempfile.mkdtemp(prefix="fangtype_te_"))

    run_predictions(pairs, engine, out_root, show_progress)
    return score(pairs, out_root, tool_name)
