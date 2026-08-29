"""Pins that the mypy restore arm resolves a ``self.`` attribute target to a real type.

``build_scope_tree`` keys ``LspScope.attributes`` by the bare attribute name (``width``),
because both of its inputs -- ``_collect_structure``'s ``attr_lines`` and the name-keyed
facts ``resolve_hint_facts`` derives from inlay hints -- carry the bare name. Nothing in
this file guarded that agreement before: ``resolve_inferred_type("attribute", ...)`` could
regress to returning ``None`` for every attribute target in the mypy restore arm
(``benchmark/mypy_eval/runner.py::_evaluate_file``) without any test failing, which is
exactly the shape of an earlier real bug where ``workflow._create_attribute_target`` named
the target dotted (``self.width``) while ``attr_lines`` held the bare tail, so the two
names never matched. This drives the real Jedi engine and inlay-hint generator (the same
inference pipeline the shipped server runs, not a hand-built hint tuple) through both
``build_scope_tree`` and ``resolve_inferred_type``, and asserts a concrete resolved type
rather than merely a non-``None``/non-empty result, so a reintroduced dotted/bare mismatch
fails this test instead of silently reappearing.
"""

from __future__ import annotations

from benchmark.lsp_client.shim import (
    _hint_tuples,
    build_scope_tree,
    resolve_hint_facts,
    resolve_inferred_type,
)
from fangtype.utils.inlay_hint_helper import InlayHintHelper


def _server_hints(engine, source: str) -> list[tuple[int, int, str, bool]]:
    helper = InlayHintHelper.__new__(InlayHintHelper)  # bypass the @inject constructor
    result = engine.infer_types(source)
    hints = [
        hint
        for scope in result.scope_tree.scopes_by_id.values()
        for hint in helper.generate_hints_for_scope(scope, source)
    ]
    return sorted(_hint_tuples(hints))


def test_a_self_attribute_target_resolves_to_its_type_through_the_full_pipeline(engine) -> None:
    """The mypy restore arm's exact call shape: ``build_scope_tree`` then ``resolve_inferred_type``
    with ``target_kind="attribute"`` and a *dotted* ``variable_name``, matching what a mypy
    ground-truth manifest target carries (``self.width``, never the bare ``width``)."""
    source = (
        "class Box:\n"
        "    def __init__(self):\n"
        "        self.width = 3\n"
        "\n"
        "    def area(self, h):\n"
        "        return self.width * h\n"
    )
    hints = _server_hints(engine, source)
    facts, _dropped = resolve_hint_facts(source, hints)

    tree = build_scope_tree(source, hints, facts)
    resolved = resolve_inferred_type(
        tree,
        target_kind="attribute",
        line_number=3,  # 1-based line of "self.width = 3"
        variable_name="self.width",
        function_name=None,
        parameter_name=None,
    )

    assert resolved == "int"
