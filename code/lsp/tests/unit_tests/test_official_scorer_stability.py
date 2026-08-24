"""The official TypeEvalPy scorer sorts facts, so input order cannot change a score."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from benchmark.typeevalpy import official

if TYPE_CHECKING:
    from pathlib import Path


def _fact(line: int, types: list[str], variable: str = "x") -> dict[str, object]:
    return {
        "file": "main.py",
        "line_number": line,
        "variable": variable,
        "type": list(types),
    }


def test_sort_facts_orders_lines_and_type_lists() -> None:
    facts = [_fact(3, ["str", "int"]), _fact(1, ["bool"])]
    ordered = official.sort_facts(facts)
    assert [int(fact["line_number"]) for fact in ordered] == [1, 3]
    assert ordered[1]["type"] == ["int", "str"]


def test_measure_recall_is_stable_under_fact_and_type_permutation(tmp_path: Path) -> None:
    truth = [_fact(1, ["int", "str"]), _fact(2, ["bool"])]
    predicted = [_fact(2, ["bool"]), _fact(1, ["str", "int"])]
    expected_path = tmp_path / "expected.json"
    out_path = tmp_path / "out.json"
    shuffled_path = tmp_path / "out_shuffled.json"
    expected_path.write_text(json.dumps(truth), encoding="utf-8")
    out_path.write_text(json.dumps(predicted), encoding="utf-8")
    shuffled_path.write_text(json.dumps(list(reversed(predicted))), encoding="utf-8")

    first, _, _ = official.measure_recall(str(out_path), str(expected_path), "fangtype")
    second, _, _ = official.measure_recall(str(shuffled_path), str(expected_path), "fangtype")
    assert first["num_caught_exact"] == second["num_caught_exact"] == 2
    assert first["num_all"] == second["num_all"] == 2
