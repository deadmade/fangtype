"""Restore-scorer latent faults, and the committed JSON they do not move."""

from __future__ import annotations

import ast
import json
from pathlib import Path

from benchmark.mypy_eval.normalizer import normalize_annotation

_RESTORE_JSON = (
    Path(__file__).resolve().parents[4] / "thesis" / "evaluation" / "data" / "mypy_restore.json"
)


def _flatten_unions(annotation: str) -> str:
    """Normalize, then collapse nested ``|`` so ``None | (None | int)`` becomes ``None | int``."""
    normalized = normalize_annotation(annotation)
    try:
        node = ast.parse(normalized, mode="eval").body
    except SyntaxError:
        return normalized

    def members(expr: ast.expr) -> list[str]:
        if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.BitOr):
            return members(expr.left) + members(expr.right)
        return [ast.unparse(expr)]

    return " | ".join(sorted(set(members(node))))


def _dotted_pairs(annotation: str) -> set[tuple[str, str]]:
    """``(module, name)`` pairs for one-level ``module.Name`` forms in ``annotation``."""
    try:
        tree = ast.parse(annotation, mode="eval")
    except SyntaxError:
        return set()
    found: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            found.add((node.value.id, node.attr))
    return found


def test_qualifier_strip_collapses_different_modules() -> None:
    assert normalize_annotation("foo.Bar") == normalize_annotation("baz.Bar") == "Bar"
    assert normalize_annotation("mypy.types.Type") == "type"


def test_optional_fold_is_not_recursive() -> None:
    assert normalize_annotation("Optional[int]") == "None | int"
    assert normalize_annotation("Optional[Optional[int]]") == "None | (None | int)"
    assert _flatten_unions("Optional[Optional[int]]") == "None | int"


def test_committed_restore_has_no_cross_module_match_and_no_flatten_flip() -> None:
    payload = json.loads(_RESTORE_JSON.read_text(encoding="utf-8"))
    cross_module_matches = 0
    flatten_flips = 0
    for target in payload["target_results"]:
        expected = target["expected_annotation"]
        inferred = target["inferred_annotation"]
        if target["status"] == "match":
            left = {name: module for module, name in _dotted_pairs(expected)}
            right = {name: module for module, name in _dotted_pairs(inferred or "")}
            shared = set(left) & set(right)
            if any(left[name] != right[name] for name in shared):
                cross_module_matches += 1
        elif target["status"] == "mismatch" and inferred is not None:
            if _flatten_unions(expected) == _flatten_unions(inferred):
                flatten_flips += 1
    assert cross_module_matches == 0
    assert flatten_flips == 0
