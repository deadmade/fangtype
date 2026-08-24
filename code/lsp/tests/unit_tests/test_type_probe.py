"""Tests for the TypeProbe abstraction."""

import ast

import jedi

from fangtype.inference.caching_probe import CachingProbe
from fangtype.inference.jedi.probe import JediProbe


def _first_expr(source: str, target_line: int) -> ast.expr:
    """Return the value expression of the assignment on the given 1-based line."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and node.lineno == target_line:
            return node.value
    raise AssertionError(f"no assignment on line {target_line}")


def test_jedi_probe_infers_literal_expression():
    source = "value = 42\n"
    script = jedi.Script(code=source)
    probe = JediProbe(script)
    expr = _first_expr(source, 1)
    assert probe.infer_expr_type(expr) == "int"


def test_jedi_probe_returns_unknown_for_unresolvable():
    source = "value = some_undefined_name\n"
    script = jedi.Script(code=source)
    probe = JediProbe(script)
    expr = _first_expr(source, 1)
    assert probe.infer_expr_type(expr) == "Unknown"


def test_caching_probe_calls_inner_once_per_position():
    class _Counter:
        def __init__(self) -> None:
            self.n = 0

        def infer_expr_type(self, expr: ast.expr) -> str:
            self.n += 1
            return "int"

    source = "value = 42\n"
    expr = _first_expr(source, 1)
    inner = _Counter()
    cached = CachingProbe(inner)
    assert cached.infer_expr_type(expr) == "int"
    assert cached.infer_expr_type(expr) == "int"
    assert inner.n == 1, "second lookup at same position must hit the cache"
