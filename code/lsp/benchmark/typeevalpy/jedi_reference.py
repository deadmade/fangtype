"""Reproduce the bundled TypeEvalPy Jedi target tool locally, scored through the
IDENTICAL official-scoring path (``runner.enumerate_pairs`` / ``runner.score``) that
``run_inference_benchmark`` uses for fangtype.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

from benchmark.typeevalpy import official
from benchmark.typeevalpy.inference_runner import (
    InferenceScore,
    _result_path,
    enumerate_pairs,
    score,
)

# benchmark/typeevalpy/jedi_reference.py -> parents[1] == benchmark/
JEDI_SRC = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "TypeEvalPy"
    / "src"
    / "target_tools"
    / "jedi"
    / "src"
)
if str(JEDI_SRC) not in sys.path:
    sys.path.insert(0, str(JEDI_SRC))

from jedi_type_inference import TypeInferenceJedi  # noqa: E402

_PROGRESS_EVERY = 25


def jedi_facts(py_path: Path) -> list[dict]:
    """Run the bundled TypeEvalPy Jedi target tool on a single file."""
    with tempfile.TemporaryDirectory(prefix="jedi_isolate_") as tmp_dir:
        isolated_dir = Path(tmp_dir) / py_path.parent.name
        shutil.copytree(py_path.parent, isolated_dir)
        isolated_path = isolated_dir / py_path.name
        inferer = TypeInferenceJedi(name=isolated_path, entry_point=isolated_path)
        inferer.infer_types()
        return inferer.get_types()


def run_jedi_predictions(
    pairs: list[tuple[Path, Path]], out_root: Path, show_progress: bool = True
) -> None:
    """Run the Jedi reference tool over every pair, writing one ``*_result.json`` each."""
    if not pairs:
        return

    total = len(pairs)
    for i, (py_path, _gt_path) in enumerate(pairs, start=1):
        try:
            facts = jedi_facts(py_path)
        except Exception:
            facts = []

        serializable_facts = [
            {k: (list(v) if isinstance(v, set) else v) for k, v in fact.items()} for fact in facts
        ]
        serializable_facts = official.sort_facts(serializable_facts)

        result_path = _result_path(py_path, out_root)
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(serializable_facts, indent=2))

        if show_progress and i % _PROGRESS_EVERY == 0:
            print(f"Progress: [{i}/{total}] ({i / total * 100:.1f}%)")

    if show_progress:
        print(f"Progress: [{total}/{total}] (100.0%)")


def run_jedi_benchmark(
    benchmark_dir: Path | None = None,
    out_root: Path | None = None,
    show_progress: bool = True,
) -> InferenceScore:
    """Run the Jedi reference tool end to end and score it -- the validation anchor."""
    pairs = enumerate_pairs(benchmark_dir)
    if not pairs:
        msg = "No benchmark files found"
        raise ValueError(msg)

    if out_root is None:
        out_root = Path(tempfile.mkdtemp(prefix="jedi_te_"))

    run_jedi_predictions(pairs, out_root, show_progress)
    return score(pairs, out_root, tool_name="jedi")
