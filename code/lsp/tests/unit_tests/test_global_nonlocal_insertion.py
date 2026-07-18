"""Regression: never annotate a global/nonlocal-declared var (SyntaxError corrupts whole file)."""

import ast

from fangtype.inference.jedi.scope_builder import collect_declared_global_nonlocal

from ._insertion_helpers import _insert_all_variables

# Canonical case: inner `x` is nonlocal (unannotatable); outer's own `x` is annotatable.
_NONLOCAL_SRC = (
    "def outer():\n"
    "    x = 0\n"
    "    def inner():\n"
    "        nonlocal x\n"
    "        x = 1\n"
    "        return x\n"
    "    return inner()\n"
)

# `global` variant: module-level `counter` is annotatable, the in-function rebinding is not.
_GLOBAL_SRC = "counter = 0\ndef bump():\n    global counter\n    counter = 1\n"


class TestCollectDeclaredGlobalNonlocal:
    """Unit coverage for the scope-boundary-respecting collector."""

    def test_collects_nonlocal(self) -> None:
        node = ast.parse("def f():\n    nonlocal x\n    x = 1\n").body[0]
        assert collect_declared_global_nonlocal(node) == {"x"}

    def test_collects_global(self) -> None:
        node = ast.parse("def f():\n    global g\n    g = 1\n").body[0]
        assert collect_declared_global_nonlocal(node) == {"g"}

    def test_multiple_names_across_both_statements(self) -> None:
        node = ast.parse("def f():\n    global a, b\n    nonlocal c\n").body[0]
        assert collect_declared_global_nonlocal(node) == {"a", "b", "c"}

    def test_descends_through_compound_statements(self) -> None:
        # A declaration applies to the whole function body wherever it appears.
        src = "def f():\n    if cond:\n        for i in it:\n            global g\n"
        node = ast.parse(src).body[0]
        assert collect_declared_global_nonlocal(node) == {"g"}

    def test_does_not_leak_from_nested_function(self) -> None:
        # `x` is nonlocal only inside `inner`; `outer` itself declares nothing.
        outer = ast.parse(_NONLOCAL_SRC).body[0]
        assert collect_declared_global_nonlocal(outer) == set()

    def test_no_declarations_is_empty(self) -> None:
        node = ast.parse("def f():\n    x = 1\n").body[0]
        assert collect_declared_global_nonlocal(node) == set()


class TestScopeBuilderRecordsDeclarations:
    """The real Jedi-driven scope tree must carry the declared names per scope."""

    def test_nonlocal_recorded_on_inner_scope_only(self, engine) -> None:
        result = engine.infer_types(_NONLOCAL_SRC)
        scopes = {s.name: s for s in result.scope_tree.scopes_by_id.values()}
        assert scopes["inner"].nonlocal_or_global_names == {"x"}
        assert scopes["outer"].nonlocal_or_global_names == set()
        assert result.scope_tree.root.nonlocal_or_global_names == set()

    def test_global_recorded_on_function_scope(self, engine) -> None:
        result = engine.infer_types(_GLOBAL_SRC)
        scopes = {s.name: s for s in result.scope_tree.scopes_by_id.values()}
        assert scopes["bump"].nonlocal_or_global_names == {"counter"}
        assert result.scope_tree.root.nonlocal_or_global_names == set()


class TestInsertionProducesCompilableOutput:
    """End-to-end: inserting every inferred variable target must not corrupt the file."""

    def test_nonlocal_case_compiles_and_leaves_inner_x_bare(self, engine) -> None:
        result = engine.infer_types(_NONLOCAL_SRC)
        modified = _insert_all_variables(_NONLOCAL_SRC, result.get_variable_insertions())
        # Would raise `annotated name 'x' can't be nonlocal` before the fix.
        compile(modified, "<test>", "exec")
        # The nonlocal rebinding stays bare; no annotation was placed on it.
        assert "        x: " not in modified

    def test_global_case_compiles_and_leaves_rebinding_bare(self, engine) -> None:
        result = engine.infer_types(_GLOBAL_SRC)
        modified = _insert_all_variables(_GLOBAL_SRC, result.get_variable_insertions())
        compile(modified, "<test>", "exec")
        assert "    counter: " not in modified  # the in-function `counter = 1` stays bare
