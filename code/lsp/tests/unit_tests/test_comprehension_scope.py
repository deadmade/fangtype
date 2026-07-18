"""Regression: comprehension loop targets suppressed from insertion only, not inference/hints."""

import ast

import jedi

from fangtype.inference.jedi.scope_builder import collect_comprehension_target_positions
from fangtype.utils.inlay_hint_helper import InlayHintHelper

from ._insertion_helpers import _insert_all_variables


def _collect(src: str) -> set[tuple[int, int, str]]:
    """Collect comprehension target positions, wiring the Jedi Script the collector now needs."""
    return collect_comprehension_target_positions(ast.parse(src), jedi.Script(code=src))


# The canonical reproducing case.
_COMPREHENSION_SRC = "result = [x*x for x in range(10)]\n"

# A real `x = 5` coexisting with a comprehension `x` (which appears first) must still insert.
_COEXISTING_REAL_ASSIGNMENT_SRC = "result = [x*x for x in range(10)]\nx = 5\n"

_NESTED_COMPREHENSION_SRC = "result = [[y for y in row] for row in matrix]\n"

_PLAIN_FOR_LOOP_SRC = "for x in range(10):\n    print(x)\n"


class TestCollectComprehensionTargetPositions:
    """Unit coverage for the scope-boundary-respecting comprehension collector."""

    def test_collects_list_comp_target(self) -> None:
        assert _collect(_COMPREHENSION_SRC) == {(0, 18, "x")}

    def test_collects_set_comp_target(self) -> None:
        positions = _collect("result = {x*x for x in range(10)}\n")
        assert {name for _, _, name in positions} == {"x"}

    def test_collects_dict_comp_target(self) -> None:
        positions = _collect("result = {x: x*x for x in range(10)}\n")
        assert {name for _, _, name in positions} == {"x"}

    def test_collects_generator_exp_target(self) -> None:
        positions = _collect("result = sum(x*x for x in range(10))\n")
        assert {name for _, _, name in positions} == {"x"}

    def test_collects_nested_comprehension_targets(self) -> None:
        positions = _collect(_NESTED_COMPREHENSION_SRC)
        assert {name for _, _, name in positions} == {"row", "y"}

    def test_does_not_leak_from_nested_function(self) -> None:
        # A comprehension inside a nested function belongs to that function's scope, not module's.
        assert _collect("def f():\n    return [x for x in range(10)]\n") == set()

    def test_no_comprehension_is_empty(self) -> None:
        assert _collect("x = 1\n") == set()

    def test_tuple_unpacking_target_records_every_name(self) -> None:
        positions = _collect("result = [a + b for a, b in pairs]\n")
        assert {name for _, _, name in positions} == {"a", "b"}

    def test_non_ascii_line_stores_codepoint_col_not_byte_col(self) -> None:
        # `é` is 2 UTF-8 bytes; the target `x` sits at code-point col 18 but byte col 19.
        # The stored col must be the code-point col so it matches TypeInfo.col in suppression.
        assert _collect("rézult = [x*x for x in range(10)]\n") == {(0, 18, "x")}


class TestScopeBuilderRecordsAndPreservesInference:
    """Scope records positions AND keeps the type in ``scope.variables``; only insert filtered."""

    def test_position_recorded_on_module_scope(self, engine) -> None:
        result = engine.infer_types(_COMPREHENSION_SRC)
        module = result.scope_tree.root
        assert (0, 18, "x") in module.comprehension_target_positions

    def test_scope_variables_still_carries_the_comprehension_type(self, engine) -> None:
        """The clarified requirement: inference must NOT lose the comprehension var."""
        result = engine.infer_types(_COMPREHENSION_SRC)
        module = result.scope_tree.root
        assert "x" in module.variables
        assert module.variables["x"].type_str == "int"

    def test_inlay_hint_still_shows_comprehension_var_type(self, engine) -> None:
        """The clarified requirement, from the hint-generation path directly."""
        result = engine.infer_types(_COMPREHENSION_SRC)
        module = result.scope_tree.root
        helper = InlayHintHelper.__new__(InlayHintHelper)  # bypass @inject constructor
        hints = helper.generate_hints_for_scope(module, _COMPREHENSION_SRC, None, "module")
        var_hints = [
            h
            for h in hints
            if isinstance(h.label, str) and h.label.strip() == "int" and h.position.line == 0
        ]
        assert var_hints, f"expected an int hint at line 0, got: {hints}"


class TestGetVariableInsertionsSkipsComprehensionTarget:
    """The insertion surface must drop the comprehension var while keeping siblings."""

    def test_result_emitted_but_x_is_not(self, engine) -> None:
        result = engine.infer_types(_COMPREHENSION_SRC)
        insertions = result.get_variable_insertions()
        assert (0, "result") in insertions
        assert insertions[(0, "result")] == "list[int]"
        assert (0, "x") not in insertions
        assert all(name != "x" for _, name in insertions)

    def test_does_not_over_suppress_a_real_coexisting_assignment(self, engine) -> None:
        result = engine.infer_types(_COEXISTING_REAL_ASSIGNMENT_SRC)
        insertions = result.get_variable_insertions()
        # The real `x = 5` on line 1 (0-based) is still an insertion target.
        assert (1, "x") in insertions
        assert insertions[(1, "x")] == "int"
        # The comprehension `x` at line 0 col 18 must never appear.
        assert (0, "x") not in insertions

    def test_nested_comprehension_leaks_neither_row_nor_y(self, engine) -> None:
        result = engine.infer_types(_NESTED_COMPREHENSION_SRC)
        insertions = result.get_variable_insertions()
        names = {name for _, name in insertions}
        assert "row" not in names
        assert "y" not in names
        assert "result" in names

    def test_plain_for_loop_variable_still_annotatable(self, engine) -> None:
        """Regression: the comprehension filter must not swallow real for-loop vars."""
        result = engine.infer_types(_PLAIN_FOR_LOOP_SRC)
        insertions = result.get_variable_insertions()
        assert any(name == "x" for _, name in insertions)


class TestInsertionProducesCompilableOutput:
    """End-to-end: inserting all vars leaves comprehension line untouched but annotates siblings."""

    def test_comprehension_line_unchanged_result_annotated_and_compiles(self, engine) -> None:
        result = engine.infer_types(_COMPREHENSION_SRC)
        modified = _insert_all_variables(_COMPREHENSION_SRC, result.get_variable_insertions())
        compile(modified, "<test>", "exec")
        assert "result: list[int] = [x*x for x in range(10)]" in modified
        # No annotation was placed on the comprehension's loop target.
        assert "x: int" not in modified

    def test_coexisting_real_assignment_is_annotated_and_compiles(self, engine) -> None:
        result = engine.infer_types(_COEXISTING_REAL_ASSIGNMENT_SRC)
        modified = _insert_all_variables(
            _COEXISTING_REAL_ASSIGNMENT_SRC, result.get_variable_insertions()
        )
        compile(modified, "<test>", "exec")
        assert "x: int = 5" in modified

    def test_nested_comprehension_compiles_with_no_leaked_annotation(self, engine) -> None:
        source = "matrix = [[1, 2], [3, 4]]\n" + _NESTED_COMPREHENSION_SRC
        result = engine.infer_types(source)
        modified = _insert_all_variables(source, result.get_variable_insertions())
        compile(modified, "<test>", "exec")
        assert "row:" not in modified
        assert "y:" not in modified
