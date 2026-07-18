"""Score TypeEvalPy facts with the vendored upstream submodule's own scorer."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_SUB_SRC = Path(__file__).resolve().parents[1] / "data" / "TypeEvalPy" / "src"
if str(_SUB_SRC) not in sys.path:
    sys.path.insert(0, str(_SUB_SRC))

import result_analyzer.analysis_utils as _au  # noqa: E402

_MATCH_KEYS = ("file", "line_number", "function", "parameter", "variable")


def _is_same_element(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Match two facts on file/line/discriminator only -- see module docstring."""
    return all(a.get(k) == b.get(k) for k in _MATCH_KEYS)


_au.is_same_element = _is_same_element

# Thin re-exports so callers never import the submodule directly.
check_match = _au.check_match
measure_recall = _au.measure_recall
equal_sound = _au.equal_sound
equal_complete = _au.equal_complete
categorize_facts = _au.categorize_facts
sort_facts = _au.sort_facts
