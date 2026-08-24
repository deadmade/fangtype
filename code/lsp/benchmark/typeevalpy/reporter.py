"""Summarize and export JSON for the official-scoring inference run."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from benchmark.typeevalpy.inference_runner import InferenceScore
    from benchmark.typeevalpy.insertion_runner import InsertionScore


def summarize(
    score: InferenceScore | InsertionScore,
    lenient: InferenceScore | None = None,
    reference: InferenceScore | None = None,
    *,
    exact_label: str = "Exact recall",
) -> str:
    """One plain-text block describing a finished TypeEvalPy run.

    The committed artefact is the JSON that ``export_json`` writes, and the thesis
    macros are generated from it by ``thesis/evaluation/generate_tables.py``. This
    exists so an operator can see what a run produced without opening the JSON, so it
    stays a summary and never becomes a second source of truth.

    ``lenient`` and ``reference``, when given, add the concept-lenient companion and
    the Jedi comparison as extra lines rather than separate blocks.
    """
    lines = [
        f"Tool               {score.tool_name}",
        f"Files              {score.file_count}",
        f"Facts              {score.num_all}",
        f"{exact_label:<18} {score.num_caught_exact} ({score.exact_pct:.1f}%)",
        f"Partial            {score.num_caught_partial}",
    ]
    for category, counts in sorted(score.per_category.items()):
        num_all = counts.get("num_all", 0)
        caught = counts.get("num_caught_exact", 0)
        share = (caught / num_all * 100) if num_all else 0.0
        lines.append(f"  {category:<16} {caught}/{num_all} ({share:.1f}%)")
    if lenient is not None:
        lines.append(
            f"Concept-lenient    {lenient.num_caught_exact}/{lenient.num_all} "
            f"({lenient.exact_pct:.1f}%), "
            f"{lenient.exact_pct - score.exact_pct:+.1f} pp against strict"
        )
    if reference is not None:
        lines.append(
            f"Reference          {reference.tool_name} "
            f"{reference.num_caught_exact}/{reference.num_all} "
            f"({reference.exact_pct:.1f}%), "
            f"{score.exact_pct - reference.exact_pct:+.1f} pp for {score.tool_name}"
        )
    return "\n".join(lines)


def export_json(
    score: InferenceScore | InsertionScore,
    output_path: Path,
    lenient: InferenceScore | None = None,
    *,
    engine: str | None = None,
    gate_enabled: bool | None = None,
    fangtype_revision: str | None = None,
    typeevalpy_revision: str | None = None,
    toolchain: dict[str, str | bool] | None = None,
) -> None:
    """Export the ``InferenceScore`` fields (plus ``exact_pct``) as JSON.

    ``lenient`` is the concept-lenient companion from ``generate_lenient_companion``.
    It is exported alongside the strict score so the thesis macros can cite it from a
    committed artefact instead of a number read off stdout. Runs without a companion
    (the Jedi reference, the insertion modes) omit the three keys entirely.

    ``engine`` and ``gate_enabled`` record the configuration that produced the run. A
    gate-on and a gate-off artefact are otherwise schema-identical, so without them the
    only thing separating the two is the filename an operator typed on ``--output``.

    ``typeevalpy_revision`` records the commit of the TypeEvalPy submodule that was
    scored, the counterpart of the ``mypy_revision`` the mypy artefacts carry. Without
    it the corpus a run scored is unrecoverable from the artefact, and the revision the
    thesis cites for it could only ever be taken on the operator's word.

    ``fangtype_revision`` records the commit of this repository that produced the run,
    so a pin claimed in the thesis prose can be checked against the artefact rather than
    taken on the operator's word. ``fangtype_revision`` alone cannot show an uncommitted
    change, since it only ever reads HEAD, so pass a ``fangtype_dirty`` key inside
    ``toolchain`` from ``is_working_tree_dirty`` alongside it. Artefacts exported before
    ``fangtype_dirty`` existed carry no dirtiness record at all, neither ``True`` nor
    ``False``; that key is simply absent from them, and no reader here fills it back in.
    ``toolchain`` otherwise carries the Jedi/mypy/CPython versions of the same run, from
    ``build_toolchain_pins``.
    """
    data = asdict(score)
    data["out_root"] = str(score.out_root)
    data["exact_pct"] = score.exact_pct
    if engine is not None:
        data["engine"] = engine
    if gate_enabled is not None:
        data["gate_enabled"] = gate_enabled
    if fangtype_revision is not None:
        data["fangtype_revision"] = fangtype_revision
    if typeevalpy_revision is not None:
        data["typeevalpy_revision"] = typeevalpy_revision
    if toolchain is not None:
        data.update(toolchain)
    if lenient is not None:
        data["lenient_num_all"] = lenient.num_all
        data["lenient_num_caught_exact"] = lenient.num_caught_exact
        data["lenient_exact_pct"] = lenient.exact_pct

    output_path.write_text(json.dumps(data, indent=2))
    print(f"Exported detailed results to {output_path}")
