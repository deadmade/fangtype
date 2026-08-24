"""Cancel-token threading in Jedi inference: partial on cancel, never cached, fallback token."""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

import jedi

import fangtype.inference.jedi.engine as engine_mod
import fangtype.inference.jedi.scope_builder as scope_builder_mod
from fangtype.cancellation import CancellationToken
from fangtype.inference.jedi.engine import JediInferenceEngine
from fangtype.utils.settings import Settings

if TYPE_CHECKING:
    from fangtype.inference.inference_result import InferenceResult


# CancellationToken flag semantics -------------------------------------------


class TestCancellationToken:
    """The cooperative cancel flag: fresh, set-on-cancel, idempotent."""

    def test_fresh_token_is_not_cancelled(self):
        token = CancellationToken()
        assert token.cancelled() is False

    def test_cancel_sets_the_flag(self):
        token = CancellationToken()
        assert token.cancelled() is False
        token.cancel()
        assert token.cancelled() is True

    def test_cancel_is_idempotent(self):
        token = CancellationToken()
        token.cancel()
        token.cancel()
        assert token.cancelled() is True


SRC = "def add(a, b):\n    r = a + b\n    return r\n"

MULTI_NAME_SRC = (
    "def add(a, b):\n"
    "    x = a + b\n"
    "    y = x * 2\n"
    "    return y\n"
    "\n"
    "def greet(name):\n"
    "    msg = 'hi'\n"
    "    return msg\n"
    "\n"
    "z = add(1, 2)\n"
    "w = greet('bob')\n"
)


ATTR_CALL_SRC = (
    "class C:\n"
    "    def __init__(self):\n"
    "        self.a = make()\n"
    "        self.b = build()\n"
    "\n"
    "def make():\n"
    "    return 1\n"
    "\n"
    "def build():\n"
    "    return 2\n"
)


def _cancelled_token() -> CancellationToken:
    """A token that reports ``cancelled()`` immediately."""
    token = CancellationToken()
    token.cancel()
    return token


def _populated_slot_count(result: InferenceResult) -> int:
    """Count parameters + variable assignments that carry a real (non-Unknown) type."""
    count = 0
    for scope in result.scope_tree.scopes_by_id.values():
        for type_info in scope.parameters.values():
            if type_info.type_str not in ("", "Unknown"):
                count += 1
        for history in scope.variable_history.values():
            for type_info in history:
                if type_info.type_str not in ("", "Unknown"):
                    count += 1
    return count


# 1. Cancelled -> partial ----------------------------------------------------


def test_cancelled_token_returns_partial_with_fewer_names():
    full = JediInferenceEngine(Settings()).infer_types(MULTI_NAME_SRC, path="/tmp/b2_partial.py")

    partial = JediInferenceEngine(Settings()).infer_types(
        MULTI_NAME_SRC, path="/tmp/b2_partial.py", cancel_token=_cancelled_token()
    )

    # Returns cleanly with the module scope present ...
    assert "module" in partial.scope_tree.scopes_by_id
    assert partial.scope_tree.root.scope_type.value == "module"
    # ... but with strictly fewer populated slots than the full run.
    assert _populated_slot_count(full) > 0
    assert _populated_slot_count(partial) < _populated_slot_count(full)


# 2. Engine is pure compute (no result cache) -------------------------------


def test_engine_recomputes_and_never_serves_a_stale_partial():
    """Engine is pure compute: cancel yields a partial; a later clean call recomputes the tree."""
    eng = JediInferenceEngine(Settings())

    partial = eng.infer_types(
        MULTI_NAME_SRC, path="/tmp/b2_cache.py", cancel_token=_cancelled_token()
    )
    full = eng.infer_types(MULTI_NAME_SRC, path="/tmp/b2_cache.py")

    assert _populated_slot_count(full) > 0
    assert _populated_slot_count(full) > _populated_slot_count(partial)


# 3. Protocol optionality ----------------------------------------------------


def test_infer_types_cancel_token_is_optional_and_uncancelled():
    without = JediInferenceEngine(Settings()).infer_types(MULTI_NAME_SRC, path="/tmp/b2_opt.py")
    assert _populated_slot_count(without) > 0

    fresh = CancellationToken()  # never cancelled
    with_token = JediInferenceEngine(Settings()).infer_types(
        MULTI_NAME_SRC, path="/tmp/b2_opt.py", cancel_token=fresh
    )
    assert _populated_slot_count(with_token) > 0

    # A fresh (never-cancelled) token is behaviourally identical to None.
    assert _populated_slot_count(with_token) == _populated_slot_count(without)


# 4. Post-loop passes bounded ------------------------------------------------


def test_build_scope_tree_skips_post_loop_passes_when_cancelled(monkeypatch):
    called: list[str] = []

    monkeypatch.setattr(
        scope_builder_mod,
        "apply_override_inference",
        lambda *a, **k: called.append("override"),
    )
    monkeypatch.setattr(
        scope_builder_mod,
        "apply_contract_propagation",
        lambda *a, **k: called.append("contract"),
    )
    monkeypatch.setattr(
        scope_builder_mod,
        "propagate_call_flow_types",
        lambda *a, **k: called.append("call_flow"),
    )

    tree = ast.parse(MULTI_NAME_SRC)
    script = jedi.Script(MULTI_NAME_SRC, path="/tmp/b2_guard.py")

    result_tree = scope_builder_mod.build_scope_tree(script, tree, cancel_token=_cancelled_token())

    # None of the expensive post-loop passes ran (guard-and-return fired first).
    assert called == []
    # A valid partial tree is still returned.
    assert "module" in result_tree.scopes_by_id


def test_build_scope_tree_runs_post_loop_passes_when_uncancelled(monkeypatch):
    called: list[str] = []

    monkeypatch.setattr(
        scope_builder_mod,
        "apply_override_inference",
        lambda *a, **k: called.append("override"),
    )
    monkeypatch.setattr(
        scope_builder_mod,
        "apply_contract_propagation",
        lambda *a, **k: called.append("contract"),
    )
    monkeypatch.setattr(
        scope_builder_mod,
        "propagate_call_flow_types",
        lambda *a, **k: called.append("call_flow"),
    )

    tree = ast.parse(MULTI_NAME_SRC)
    script = jedi.Script(MULTI_NAME_SRC, path="/tmp/b2_guard_ok.py")

    # No token (uncancelled): all three post-loop passes must run.
    scope_builder_mod.build_scope_tree(script, tree)

    assert called == ["override", "contract", "call_flow"]


# 5. Secondary methods honor the fallback cancel token -----------------------


def _patch_fallback_token_cancelled(monkeypatch) -> None:
    """Force the engine's fallback ``CancellationToken()`` (built when cancel_token=None) set."""
    cancelled = _cancelled_token()
    monkeypatch.setattr(engine_mod, "CancellationToken", lambda *a, **k: cancelled)


def test_infer_types_at_locations_consults_fallback_and_bails(monkeypatch):
    _patch_fallback_token_cancelled(monkeypatch)

    infer_calls: list[tuple] = []
    real_infer = jedi.Script.infer

    def counting_infer(self, *args, **kwargs):
        infer_calls.append((args, kwargs))
        return real_infer(self, *args, **kwargs)

    monkeypatch.setattr(jedi.Script, "infer", counting_infer)

    eng = JediInferenceEngine(Settings())
    result = eng.infer_types_at_locations(SRC, [(1, 4), (2, 4), (3, 11)], path="/tmp/b2_loc.py")

    # The fallback token was already cancelled, so the loop broke before probing.
    assert infer_calls == []
    assert result == {}


def test_secondary_methods_are_callable_with_explicit_cancel_token():
    """Sanity: infer_types_at_locations accepts an explicit cancel_token= keyword."""
    eng = JediInferenceEngine(Settings())
    fresh = CancellationToken()

    locations = eng.infer_types_at_locations(
        SRC, [(1, 4)], path="/tmp/b2_loc_ok.py", cancel_token=fresh
    )
    assert isinstance(locations, dict)


# 6. Post-loop INTERNALS bounded: guard checks at ENTRY only, so cancelled passes run, no infer.


def _count_infer_calls(monkeypatch) -> list[tuple]:
    """Install a spy on ``jedi.Script.infer`` and return the (empty) call log."""
    infer_calls: list[tuple] = []
    real_infer = jedi.Script.infer

    def counting_infer(self, *args, **kwargs):
        infer_calls.append((args, kwargs))
        return real_infer(self, *args, **kwargs)

    monkeypatch.setattr(jedi.Script, "infer", counting_infer)
    return infer_calls


def test_infer_function_call_assignments_stops_when_cancelled(monkeypatch):
    tree = ast.parse(MULTI_NAME_SRC)
    script = jedi.Script(MULTI_NAME_SRC, path="/tmp/b2_add_calls.py")

    # Build the full tree first (uncancelled) so the pass has scopes to update.
    scope_tree = scope_builder_mod.build_scope_tree(script, tree)

    # Spy only from here: count solely the calls made by the direct re-run below.
    infer_calls = _count_infer_calls(monkeypatch)

    # Re-run call-assignment pass cancelled: the guard breaks ast.walk before any Jedi inference.
    scope_builder_mod._infer_function_call_assignments(
        tree, scope_tree, script, cancel_token=_cancelled_token()
    )

    assert infer_calls == []


def test_extract_attributes_stops_when_cancelled(monkeypatch):
    tree = ast.parse(ATTR_CALL_SRC)
    script = jedi.Script(ATTR_CALL_SRC, path="/tmp/b2_add_attrs.py")

    # Build the full tree first (uncancelled) so method scopes exist.
    scope_tree = scope_builder_mod.build_scope_tree(script, tree)

    infer_calls = _count_infer_calls(monkeypatch)

    # Re-run attribute pass cancelled: the guard breaks ast.walk before any self.attr is inferred.
    scope_builder_mod._extract_attributes(
        tree, scope_tree, {}, scope_tree.root, script, cancel_token=_cancelled_token()
    )

    assert infer_calls == []
