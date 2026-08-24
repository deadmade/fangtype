"""Tests for InferenceResult.get_variable_insertions per-binding enumeration."""

import ast

import pytest

from fangtype.analysis import Scope, ScopeType, TypeInfo, TypeSource
from fangtype.analysis.types import ScopeTree
from fangtype.inference.inference_result import InferenceResult
from fangtype.inference.jedi.engine import JediInferenceEngine

# `a` reassigned thrice; TypeEvalPy wants one fact per binding but default reports only the last.
_REASSIGN_SOURCE = "a = f1\na = f2\na = f3\n"


def _make_reassigned_result() -> InferenceResult:
    tree = ast.parse(_REASSIGN_SOURCE)
    module = Scope(scope_id="module", scope_type=ScopeType.MODULE, name="module", ast_node=tree)
    for line_0 in (0, 1, 2):
        module.add_variable(
            "a",
            TypeInfo(type_str="Callable", source=TypeSource.LITERAL, line=line_0, col=0),
        )
    scope_tree = ScopeTree(root=module)
    scope_tree.add_scope(module)
    return InferenceResult(scope_tree=scope_tree, source=_REASSIGN_SOURCE)


def test_get_variable_insertions_default_collapses_to_last_binding() -> None:
    """Default (per_binding=False) keeps the current one-per-name (last) behavior."""
    result = _make_reassigned_result()
    insertions = result.get_variable_insertions()
    assert insertions == {(2, "a"): "Callable"}


def test_get_variable_insertions_per_binding_emits_every_site() -> None:
    """per_binding=True emits a (line, name) entry for every assignment site."""
    result = _make_reassigned_result()
    insertions = result.get_variable_insertions(per_binding=True)
    assert insertions == {
        (0, "a"): "Callable",
        (1, "a"): "Callable",
        (2, "a"): "Callable",
    }


def test_get_variable_insertion_candidates_orders_most_recent_first() -> None:
    """Candidates for a name are its bindings, most-recent-first, grouped by scope."""
    result = _make_reassigned_result()
    candidates = result.get_variable_insertion_candidates()
    assert candidates == {("module", "a"): [(2, "Callable"), (1, "Callable"), (0, "Callable")]}


def _make_last_unknown_result() -> InferenceResult:
    """`a` is typed at line 0 but its most-recent write (line 1) is Unknown."""
    source = "a = typed()\na = unknown()\n"
    tree = ast.parse(source)
    module = Scope(scope_id="module", scope_type=ScopeType.MODULE, name="module", ast_node=tree)
    module.add_variable("a", TypeInfo(type_str="int", source=TypeSource.LITERAL, line=0, col=0))
    module.add_variable("a", TypeInfo(type_str="Unknown", source=TypeSource.UNKNOWN, line=1, col=0))
    scope_tree = ScopeTree(root=module)
    scope_tree.add_scope(module)
    return InferenceResult(scope_tree=scope_tree, source=source)


def test_get_variable_insertion_candidates_drops_unknown_bindings() -> None:
    """An Unknown most-recent write is skipped so an earlier typed binding survives."""
    result = _make_last_unknown_result()
    assert result.get_variable_insertion_candidates() == {("module", "a"): [(0, "int")]}


def test_get_variable_insertion_candidates_skips_nonlocal_global_names() -> None:
    """A name declared global/nonlocal is filtered from the candidate enumeration too."""
    result = _make_nonlocal_result()
    assert result.get_variable_insertion_candidates() == {}


def _make_nonlocal_result() -> InferenceResult:
    """A scope where `x` is declared global/nonlocal — it must never be a target."""
    source = "x = 1\n"
    tree = ast.parse(source)
    scope = Scope(scope_id="func:f", scope_type=ScopeType.FUNCTION, name="f", ast_node=tree)
    scope.add_variable("x", TypeInfo(type_str="int", source=TypeSource.LITERAL, line=0, col=0))
    scope.nonlocal_or_global_names = {"x"}
    scope_tree = ScopeTree(root=scope)
    scope_tree.add_scope(scope)
    return InferenceResult(scope_tree=scope_tree, source=source)


def test_get_variable_insertions_skips_nonlocal_global_names() -> None:
    """Global/nonlocal names filtered from both enumerations (annotating them is a SyntaxError)."""
    result = _make_nonlocal_result()
    assert result.get_variable_insertions() == {}
    assert result.get_variable_insertions(per_binding=True) == {}


class TestParamHasAnnotationAllKinds:
    """Bug #1: `_param_has_annotation` must scan every param bucket, not just args.args."""

    def _result(self) -> InferenceResult:
        module = Scope(
            scope_id="module", scope_type=ScopeType.MODULE, name="module", ast_node=ast.parse("")
        )
        scope_tree = ScopeTree(root=module)
        scope_tree.add_scope(module)
        return InferenceResult(scope_tree=scope_tree, source="")

    @pytest.mark.parametrize(
        ("source", "param", "expected"),
        [
            pytest.param(
                "def f(a, /, b, *args, c: int, **kw): ...", "c", True, id="kwonly_annotated"
            ),
            pytest.param("def g(x: int, /): ...", "x", True, id="posonly_annotated"),
            pytest.param("def h(*args: int, **kw: str): ...", "args", True, id="vararg_annotated"),
            pytest.param("def h(*args: int, **kw: str): ...", "kw", True, id="kwarg_annotated"),
            pytest.param(
                "def f(a, /, b, *args, c, **kw): ...", "c", False, id="kwonly_unannotated"
            ),
            pytest.param("def g(x, /): ...", "x", False, id="posonly_unannotated"),
            pytest.param("def h(*args, **kw): ...", "args", False, id="vararg_unannotated"),
            pytest.param("def f(a): ...", "a", False, id="plain_positional_unannotated"),
        ],
    )
    def test_param_has_annotation_all_kinds(self, source: str, param: str, expected: bool) -> None:
        node = ast.parse(source).body[0]
        assert self._result()._param_has_annotation(node, param) is expected


class TestGetFunctionInsertionsKwonlyRegression:
    """Bug #1 regression: real Jedi scope tree exercising the full get_function_insertions path."""

    def test_annotated_kwonly_param_not_listed_as_missing(
        self, engine: JediInferenceEngine
    ) -> None:
        source = (
            "from typing import Sequence\n\n\ndef f(*, count: Sequence[int]):\n    return count\n"
        )
        result = engine.infer_types(source)
        insertions = result.get_function_insertions()
        for info in insertions.values():
            assert "count" not in info["params"]


class TestGetAttributeInsertionsSelfKeyRegression:
    """Bug #7: bare-keyed self attrs must reconstruct `self.x` before the annotation check."""

    def test_already_annotated_self_attribute_is_skipped(self, engine: JediInferenceEngine) -> None:
        source = "class C:\n    def __init__(self):\n        self.width: int = 5\n"
        result = engine.infer_types(source)
        assert result.get_attribute_insertions() == {}

    def test_unannotated_self_attribute_is_still_returned(
        self, engine: JediInferenceEngine
    ) -> None:
        """Guard against over-suppression: a bare, un-annotated self attr must still surface."""
        source = "class C:\n    def __init__(self):\n        self.height = 5\n"
        result = engine.infer_types(source)
        assert result.get_attribute_insertions() == {(3, "height"): "int"}

    def test_already_annotated_dotted_attribute_stays_skipped(
        self, engine: JediInferenceEngine
    ) -> None:
        """Regression guard: non-self dotted keys already worked -- must keep working."""
        source = "class C:\n    def __init__(self, point):\n        point.x: int = 5\n"
        result = engine.infer_types(source)
        assert result.get_attribute_insertions() == {}


class TestInlineAnnotationDetection:
    """The already-annotated check reads the parsed tree, never the raw source line."""

    def test_lambda_parameter_colon_does_not_suppress_the_binding(
        self, engine: JediInferenceEngine
    ) -> None:
        """The `" x:"` of the lambda's own parameter used to read as an annotation on `x`.

        The editor showed a Callable ghost hint that accept-all then refused to write.
        """
        result = engine.infer_types("x = lambda x: x + 1\n")
        assert (0, "x") in result.get_variable_insertions()

    def test_lambda_with_a_differently_named_parameter_is_unaffected(
        self, engine: JediInferenceEngine
    ) -> None:
        """Guard the neighbouring shape that always worked."""
        result = engine.infer_types("y = lambda x: x + 1\n")
        assert (0, "y") in result.get_variable_insertions()

    def test_annotated_variable_is_suppressed(self, engine: JediInferenceEngine) -> None:
        """The behaviour the substring test was there for, previously untested."""
        result = engine.infer_types("x: int = 5\n")
        assert result.get_variable_insertions() == {}

    def test_annotation_in_a_trailing_comment_does_not_suppress(
        self, engine: JediInferenceEngine
    ) -> None:
        result = engine.infer_types("x = 5  # x: int\n")
        assert (0, "x") in result.get_variable_insertions()

    def test_annotation_inside_a_string_does_not_suppress(
        self, engine: JediInferenceEngine
    ) -> None:
        result = engine.infer_types('x = "x: int"\n')
        assert (0, "x") in result.get_variable_insertions()

    def test_annotation_on_another_line_does_not_suppress(
        self, engine: JediInferenceEngine
    ) -> None:
        """The check is line-precise, so a same-named annotation elsewhere must not reach."""
        result = engine.infer_types("def f():\n    x: int = 1\n\nx = 2\n")
        assert (3, "x") in result.get_variable_insertions()
