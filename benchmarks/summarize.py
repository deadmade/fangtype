"""Recompute the published benchmark summary using only the Python standard library."""

from __future__ import annotations

import gzip
import json
from collections import Counter
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"


def load(name: str) -> dict:
    path = RESULTS / name
    if path.exists():
        return json.loads(path.read_text())
    return json.loads(
        gzip.decompress(path.with_suffix(path.suffix + ".gz").read_bytes())
    )


def summarize() -> dict:
    versions = load("versions.json")
    rows = []
    for name, metric in [
        ("typeevalpy_inference.json", "TypeEvalPy inference: Fangtype"),
        ("typeevalpy_inference_jedi.json", "TypeEvalPy inference: Jedi reference"),
        ("typeevalpy_insertion.json", "TypeEvalPy insertion yield: gate on"),
        ("typeevalpy_insertion_nogate.json", "TypeEvalPy insertion yield: gate off"),
        ("mypy_restore.json", "mypy restoration: annotated context"),
        ("mypy_restore_coldstart.json", "mypy restoration: stripped context"),
        ("mypy_insert.json", "mypy insertion: gate on"),
        ("mypy_insert_nogate.json", "mypy insertion: gate off"),
    ]:
        data = load(name)
        for key in (
            "fangtype_version",
            "fangtype_revision",
            "jedi_version",
            "mypy_version",
            "python_version",
        ):
            assert data[key] == versions[key], f"Inconsistent {key} in {name}"
        assert data["fangtype_dirty"] is False, f"Dirty source tree recorded in {name}"
        if name.startswith("typeevalpy"):
            assert data["typeevalpy_revision"] == versions["typeevalpy_corpus_revision"]
            total = data["num_all"]
            exact = data["num_caught_exact"]
            assert sum(v["num_all"] for v in data["per_category"].values()) == total
            assert (
                sum(v["num_caught_exact"] for v in data["per_category"].values())
                == exact
            )
            assert abs(exact / total * 100 - data["exact_pct"]) < 1e-9
        else:
            assert data["mypy_revision"] == versions["mypy_corpus_revision"]
            targets = data["target_results"]
            outcomes = Counter(target["status"] for target in targets)
            total = len(targets)
            if name.startswith("mypy_restore"):
                exact = outcomes["match"]
                assert exact == data["typed_files"]["matched_targets"]
                assert total == data["typed_files"]["target_count"]
            else:
                exact = outcomes["inserted_correct"]
                assert exact == sum(f["inserted_correct"] for f in data["file_results"])
                assert total == sum(f["total_targets"] for f in data["file_results"])
        assert 0 <= exact <= total
        rows.append(
            {
                "metric": metric,
                "source": name,
                "matched": exact,
                "total": total,
                "percent": round(exact / total * 100, 1),
            }
        )
    census = load("mypy_annotation_census.json")
    assert (
        census["annotation_total"]
        == census["removable"] + census["skipped_declarations"]
    )
    assert all(
        row["total"] == census["removable"]
        for row in rows
        if row["source"].startswith("mypy_")
    )
    return {"fangtype_version": versions["fangtype_version"], "metrics": rows}


if __name__ == "__main__":
    print(json.dumps(summarize(), indent=2))
