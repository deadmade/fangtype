"""Issue #9: no dup hint on annotated kwonly/posonly/vararg (all land in scope.parameters)."""

from fangtype.analysis import ScopeType
from fangtype.analysis.types import TypeInfo, TypeSource
from fangtype.inference.jedi.engine import JediInferenceEngine
from fangtype.utils.inlay_hint_helper import InlayHintHelper


def _function_scope(engine: JediInferenceEngine, source: str, name: str = "f"):
    """Infer ``source`` and return the named function scope."""
    result = engine.infer_types(source)
    return next(
        scope
        for scope in result.scope_tree.scopes_by_id.values()
        if scope.scope_type == ScopeType.FUNCTION and scope.name == name
    )


def _param_hint_labels(hints: list) -> list[str]:
    """Labels of param-like hints (``": "`` separator), excluding the return hint (``" -> "``)."""
    return [h.label for h in hints if isinstance(h.label, str) and h.label.startswith(": ")]


def _return_hint(hints: list):
    """The single return-type hint (``" -> "`` separator), or None."""
    return next((h for h in hints if isinstance(h.label, str) and h.label.startswith(" -> ")), None)


class TestReturnHintAnchor:
    """The ``-> T`` hint anchors on the signature's real ')', not a string scan of the def line."""

    def test_paren_in_trailing_comment_is_not_mistaken_for_the_signature_end(self, engine) -> None:
        """A ')' in a trailing comment used to win rfind(')'), landing the hint inside it."""
        source = "def f(base):  # returns (a, b) tuple\n    return 1\n"
        func_scope = _function_scope(engine, source)
        helper = InlayHintHelper.__new__(InlayHintHelper)

        hint = _return_hint(helper.generate_hints_for_scope(func_scope, source))

        assert hint is not None
        # "def f(base)" is 11 chars; the hint belongs right after that ')', not the comment's.
        assert (hint.position.line, hint.position.character) == (0, 11)

    def test_wrapped_signature_still_gets_a_return_hint(self, engine) -> None:
        """rfind(')') returned -1 on a wrapped def line, silently dropping the hint entirely."""
        source = "def f(\n    a,\n):\n    return 1\n"
        func_scope = _function_scope(engine, source)
        helper = InlayHintHelper.__new__(InlayHintHelper)

        hint = _return_hint(helper.generate_hints_for_scope(func_scope, source))

        assert hint is not None
        # The ')' closes on its own line 2, at col 0 -> anchor just after it.
        assert (hint.position.line, hint.position.character) == (2, 1)


class TestParamHintsSkipAllAnnotatedKinds:
    """Regression for issue #9."""

    def test_kwonly_annotated_param_gets_no_duplicate_hint(self, engine) -> None:
        source = "def f(*, verbose: bool = False):\n    return verbose\n"
        func_scope = _function_scope(engine, source)
        helper = InlayHintHelper.__new__(InlayHintHelper)  # bypass @inject constructor

        hints = helper.generate_hints_for_scope(func_scope, source)

        assert _param_hint_labels(hints) == [], (
            f"expected no param hint for already-annotated kwonly 'verbose', got: {hints}"
        )

    def test_posonly_annotated_param_gets_no_duplicate_hint(self, engine) -> None:
        source = "def f(x: int, /):\n    return x\n"
        func_scope = _function_scope(engine, source)
        helper = InlayHintHelper.__new__(InlayHintHelper)

        hints = helper.generate_hints_for_scope(func_scope, source)

        assert _param_hint_labels(hints) == [], (
            f"expected no param hint for already-annotated posonly 'x', got: {hints}"
        )

    def test_annotated_vararg_and_kwarg_get_no_duplicate_hint(self, engine) -> None:
        """``*args``/``**kwargs`` land in scope.parameters as Jedi ``param``, same bug."""
        source = "def f(*args: int, **kwargs: str):\n    return args\n"
        func_scope = _function_scope(engine, source)
        helper = InlayHintHelper.__new__(InlayHintHelper)

        hints = helper.generate_hints_for_scope(func_scope, source)

        assert _param_hint_labels(hints) == [], (
            f"expected no param hint for already-annotated *args/**kwargs, got: {hints}"
        )

    def test_unannotated_sibling_param_still_gets_hinted(self, engine) -> None:
        """Regression guard: an unannotated param in the same func still gets its inferred hint."""
        source = "def f(a=1, *, verbose: bool = False):\n    return a\n"
        func_scope = _function_scope(engine, source)
        helper = InlayHintHelper.__new__(InlayHintHelper)

        hints = helper.generate_hints_for_scope(func_scope, source)

        assert _param_hint_labels(hints) == [": int"], (
            f"expected exactly one param hint (for unannotated 'a'), got: {hints}"
        )


class TestReceiverParamGetsNoHint:
    """A method's receiver is declined at insertion, so proposing it would be a dead hint."""

    def test_self_gets_no_param_hint(self, engine) -> None:
        source = (
            "class Counter:\n    def bump(self):\n        self.value = 1\n\n\nCounter().bump()\n"
        )
        func_scope = _function_scope(engine, source, name="bump")
        helper = InlayHintHelper.__new__(InlayHintHelper)

        hints = helper.generate_hints_for_scope(func_scope, source)

        assert _param_hint_labels(hints) == [], (
            f"expected no param hint for the receiver 'self', got: {hints}"
        )

    def test_cls_gets_no_param_hint(self, engine) -> None:
        source = (
            "class Counter:\n"
            "    @classmethod\n"
            "    def make(cls):\n"
            "        return cls()\n"
            "\n"
            "\nCounter.make()\n"
        )
        func_scope = _function_scope(engine, source, name="make")
        helper = InlayHintHelper.__new__(InlayHintHelper)

        hints = helper.generate_hints_for_scope(func_scope, source)

        assert _param_hint_labels(hints) == [], (
            f"expected no param hint for the receiver 'cls', got: {hints}"
        )

    def test_sibling_param_of_a_method_still_gets_hinted(self, engine) -> None:
        """Regression guard: only the receiver is dropped, not the rest of the signature."""
        source = "class Counter:\n    def add(self, n):\n        return n\n\n\nCounter().add(1)\n"
        func_scope = _function_scope(engine, source, name="add")
        helper = InlayHintHelper.__new__(InlayHintHelper)

        hints = helper.generate_hints_for_scope(func_scope, source)

        assert _param_hint_labels(hints) == [": int"], (
            f"expected exactly one param hint (for 'n'), got: {hints}"
        )

    def test_module_level_function_named_self_is_untouched(self, engine) -> None:
        """The test is positional inside a class, not the bare name anywhere it appears."""
        source = "def f(self):\n    return self\n\n\nf(1)\n"
        func_scope = _function_scope(engine, source)
        helper = InlayHintHelper.__new__(InlayHintHelper)

        hints = helper.generate_hints_for_scope(func_scope, source)

        assert _param_hint_labels(hints) == [": int"], (
            f"expected 'self' in a plain function to still be hinted, got: {hints}"
        )


def _variable_hint_labels(hints: list) -> list[tuple[int, int, str]]:
    """(line, character, label) of variable hints (a bare ``" "`` separator)."""
    return [
        (h.position.line, h.position.character, h.label)
        for h in hints
        if isinstance(h.label, str) and not h.label.startswith((": ", " -> "))
    ]


class TestVariableHintsAreEmittedPerBinding:
    """A rebound name is hinted at every binding, not only at the last one.

    ``Scope.variables`` collapses a name's history to ``types[-1]``, so the helper used to draw
    one ghost type per name. The write path already annotates any single binding, so the display
    was the part that lagged. PEP 526 still permits one annotation per name per scope, so the
    extra hints are extra offers rather than edits that can all be accepted.
    """

    def test_a_rebound_name_is_hinted_at_both_bindings_with_its_own_type(self, engine) -> None:
        """The first binding is ``int`` and the rebinding is ``str``, each on its own line."""
        source = 'def f():\n    x = 1\n    x = "s"\n    return x\n'
        func_scope = _function_scope(engine, source)
        helper = InlayHintHelper.__new__(InlayHintHelper)

        hints = helper.generate_hints_for_scope(func_scope, source)

        assert _variable_hint_labels(hints) == [(1, 5, " int"), (2, 5, " str")], (
            f"expected one hint per binding of 'x', each carrying that binding's type, got: {hints}"
        )

    def test_a_name_bound_once_still_gets_exactly_one_hint(self, engine) -> None:
        """Regression guard: iterating the history must not duplicate a single binding."""
        source = "def f():\n    x = 1\n    return x\n"
        func_scope = _function_scope(engine, source)
        helper = InlayHintHelper.__new__(InlayHintHelper)

        hints = helper.generate_hints_for_scope(func_scope, source)

        assert _variable_hint_labels(hints) == [(1, 5, " int")], (
            f"expected exactly one hint for the single binding of 'x', got: {hints}"
        )

    def test_several_type_infos_on_one_line_collapse_to_one_hint(self, engine) -> None:
        """Refinement passes append out of order, so a line can carry more than one TypeInfo.

        ``get_variable_type_at_line`` owns that tie-break and picks the last-appended entry for
        the line. The hint loop calls it once per distinct line rather than re-deciding, so the
        two rules cannot drift apart.
        """
        source = "def f():\n    x = 1\n    return x\n"
        func_scope = _function_scope(engine, source)
        func_scope.add_variable("x", TypeInfo("float", TypeSource.LITERAL, line=1, col=4))
        helper = InlayHintHelper.__new__(InlayHintHelper)

        hints = helper.generate_hints_for_scope(func_scope, source)

        assert _variable_hint_labels(hints) == [(1, 5, " float")], (
            f"expected one hint for line 1, carrying the refined type, got: {hints}"
        )

    def test_an_annotated_name_is_still_skipped_at_every_binding(self, engine) -> None:
        """The already-annotated skip is per name, so neither binding may be offered."""
        source = "def f():\n    x: int = 1\n    x = 2\n    return x\n"
        func_scope = _function_scope(engine, source)
        helper = InlayHintHelper.__new__(InlayHintHelper)

        hints = helper.generate_hints_for_scope(func_scope, source)

        assert _variable_hint_labels(hints) == [], (
            f"expected no variable hint for the annotated 'x', got: {hints}"
        )
