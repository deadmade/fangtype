"""build_scope_tree wraps the probe in CachingProbe so repeat same-position lookups hit cache."""

import ast

import jedi

from fangtype.analysis.types import ScopeTree
from fangtype.cancellation import CancellationToken
from fangtype.inference.caching_probe import CachingProbe
from fangtype.inference.jedi import scope_builder
from fangtype.protocols.type_probe_protocol import TypeProbe


def _first_expr(source: str, target_line: int) -> ast.expr:
    """Return the value expression of the assignment on the given 1-based line."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and node.lineno == target_line:
            return node.value
    raise AssertionError(f"no assignment on line {target_line}")


def _capture_call_flow_probe(monkeypatch: object, source: str) -> object:
    """Run build_scope_tree on source, capturing the probe handed to propagate_call_flow_types."""
    captured: dict[str, object] = {}
    real_propagate = scope_builder.propagate_call_flow_types

    def spy(
        tree: ast.Module,
        scope_tree: ScopeTree,
        probe: TypeProbe,
        cancel_token: CancellationToken | None = None,
    ) -> None:
        captured["probe"] = probe
        real_propagate(tree, scope_tree, probe, cancel_token)

    monkeypatch.setattr(scope_builder, "propagate_call_flow_types", spy)

    tree = ast.parse(source)
    script = jedi.Script(code=source)
    scope_builder.build_scope_tree(script, tree)

    assert "probe" in captured, "propagate_call_flow_types must be invoked"
    return captured["probe"]


def test_build_scope_tree_wraps_the_jedi_probe_in_caching_probe(monkeypatch):
    """The fixpoint must receive a CachingProbe-wrapped JediProbe, not a raw one."""
    source = "def f():\n    return 1\n"
    probe = _capture_call_flow_probe(monkeypatch, source)

    assert isinstance(probe, CachingProbe), (
        "the call-flow fixpoint must receive a CachingProbe-wrapped probe so "
        "repeated infer_expr_type lookups at the same position are memoized"
    )


def test_caching_probe_memoizes_repeated_jedi_lookups_from_the_wired_probe(monkeypatch):
    """Wired probe answers a repeat same-position lookup from cache, not via jedi.Script.infer."""
    source = "def f():\n    return 1\n\nvalue = 42\n"
    probe = _capture_call_flow_probe(monkeypatch, source)
    expr = _first_expr(source, 4)  # the `42` literal

    infer_calls = 0
    real_infer = jedi.Script.infer

    def counting_infer(self: jedi.Script, *args: object, **kwargs: object) -> object:
        nonlocal infer_calls
        infer_calls += 1
        return real_infer(self, *args, **kwargs)

    monkeypatch.setattr(jedi.Script, "infer", counting_infer)

    first = probe.infer_expr_type(expr)
    second = probe.infer_expr_type(expr)

    assert first == second == "int"
    assert infer_calls == 1, (
        "the second lookup at the same position must be served from the "
        "cache, not by calling jedi.Script.infer again "
        f"(got {infer_calls} calls)"
    )
