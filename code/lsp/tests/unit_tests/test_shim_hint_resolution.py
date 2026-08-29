"""Tests for ``resolve_hint_facts`` in benchmark/lsp_client/shim.py.

Inlay hints are position-keyed and the runners score name-keyed facts, so the whole
benchmark's ability to read inference off the channel the extension actually uses rests on
inverting a hint's anchor back to the binding it annotates. Every case below pins one
anchor shape, and the two non-ASCII cases pin the byte→code-point→UTF-16 conversion, which
no file in either corpus exercises today.
"""

import asyncio

import pytest
from lsprotocol import types

from benchmark.lsp_client.shim import _hint_tuples, resolve_hint_facts
from fangtype.analysis import NameCollector, NameLocation
from fangtype.utils.inlay_hint_helper import InlayHintHelper
from fangtype.utils.settings import Settings

# (case id, source, hints, expected facts, expected drop count).
# Hint columns are UTF-16 anchors just past the bound identifier, exactly as the server emits
# them; each is spelled out in the case's comment so a wrong column reads as a wrong test
# rather than as a wrong implementation.
CASES = [
    (
        "plain variable",
        "def f():\n    x = 1\n    return x\n",
        # "    x" ends at column 5.
        [(1, 5, "int", False)],
        [("x", "int", 1)],
        0,
    ),
    (
        "parameter on a single-line def",
        "def f(a):\n    return a\n",
        # "def f(a" ends at column 7.
        [(0, 7, "int", False)],
        [("a", "int", 0)],
        0,
    ),
    (
        "return on a single-line def",
        "def f():\n    return 1\n",
        # The signature's ')' sits at column 6, so the anchor is 7.
        [(0, 7, "int", True)],
        [("f", "int", 0)],
        0,
    ),
    (
        "self attribute resolves to its bare name",
        "class Box:\n    def __init__(self):\n        self.width = 3\n",
        # "        self.width" ends at column 18 — the end of the attribute name, not of the
        # whole "self.width" expression.
        [(2, 18, "int", False)],
        [("width", "int", 2)],
        0,
    ),
    (
        "non-ASCII in the bound name itself",
        "def f():\n    tötal = 1\n",
        # "    tötal" ends at code-point/UTF-16 column 9; its UTF-8 byte offset is 10.
        [(1, 9, "int", False)],
        [("tötal", "int", 1)],
        0,
    ),
    (
        "a byte-offset column does not match",
        "def f():\n    tötal = 1\n",
        # The same hint keyed by the raw byte offset must resolve to nothing, which is what
        # proves the conversion ran rather than coincidentally agreeing on ASCII.
        [(1, 10, "int", False)],
        [],
        1,
    ),
    (
        "non-ASCII before a parameter anchor",
        "def f(ä, b):\n    return b\n",
        # "def f(ä, b" ends at code-point column 10; the byte offset is 11.
        [(0, 10, "int", False)],
        [("b", "int", 0)],
        0,
    ),
    (
        "a wrapped signature's parameter still carries the def line",
        "def f(\n    a,\n):\n    return a\n",
        # The parameter sits on line 1, but previewInserts reported it on the def line.
        [(1, 5, "int", False)],
        [("a", "int", 0)],
        0,
    ),
    (
        "a usage hint matches no store position",
        "def f():\n    x = 1\n    return x\n",
        # "    return x" ends at column 12, a Load site, so the hint is dropped rather than
        # invented as a second binding of x.
        [(2, 12, "int", False)],
        [],
        1,
    ),
    (
        "a declaration and a usage share a label shape, only the declaration resolves",
        "def f():\n    x = 1\n    return x\n",
        # Both anchors from the two single-hint cases above, given to one call: a usage hint
        # sharing " int" with a real declaration must not be mistaken for a second binding of
        # x, nor suppress the declaration it happens to render identically to.
        [(1, 5, "int", False), (2, 12, "int", False)],
        [("x", "int", 1)],
        1,
    ),
    (
        "a usage-shaped hint at a return's own anchor still never resolves as a return",
        "def f():\n    return 1\n",
        # Same anchor as "return on a single-line def" above, but is_return is False. The
        # shim's own scraping (_hint_tuples) decides is_return from the label text alone --
        # whether it starts with "->" -- and a usage hint's label is always f" {type_str}",
        # so this can never reach the is_return branch regardless of where it sits. Position
        # disjointness is what protects the variable/attribute/parameter branches; label
        # shape is what protects this one.
        [(0, 7, "int", False)],
        [],
        1,
    ),
    (
        "a return on a wrapped signature resolves to its enclosing def",
        "def f(\n    a,\n):\n    return 1\n",
        # The anchor lands just past the ')' on line 2, which is not a def line, but line 2
        # falls inside f's own range, so the fact still carries f's def line, 0.
        [(2, 1, "int", True)],
        [("f", "int", 0)],
        0,
    ),
    (
        "a starred parameter",
        "def my_sum(a, b, *integers):\n    return a\n",
        # "def my_sum(a, b, *integers" ends at column 26. ``ast.arg.col_offset`` starts at
        # the identifier, past the star, which is where the server's anchor starts too.
        [(0, 26, "tuple", False)],
        [("integers", "tuple", 0)],
        0,
    ),
    (
        "a double-starred parameter",
        "def concatenate(**kwargs):\n    return 1\n",
        # "def concatenate(**kwargs" ends at column 24.
        [(0, 24, "dict", False)],
        [("kwargs", "dict", 0)],
        0,
    ),
    (
        "a with-item target",
        "def f(p):\n    with p as fh:\n        pass\n",
        # "    with p as fh" ends at column 16.
        [(1, 16, "int", False)],
        [("fh", "int", 1)],
        0,
    ),
    (
        "a with-item attribute target",
        "class C:\n    def m(self, p):\n        with p as self.fh:\n            pass\n",
        # "        with p as self.fh" ends at column 25, the end of the attribute name.
        [(2, 25, "int", False)],
        [("fh", "int", 2)],
        0,
    ),
    (
        "a with-item tuple target binds each element",
        "def f(p):\n    with p as (a, b):\n        pass\n",
        # "(a" ends at column 16 and "b" at column 19.
        [(1, 16, "int", False), (1, 19, "str", False)],
        [("a", "int", 1), ("b", "str", 1)],
        0,
    ),
    (
        "a comprehension target",
        "def f():\n    ys = [q for q in range(3)]\n    return ys\n",
        # The bound "q" is the one after "for", ending at column 17, not the "q" at column 11
        # that reads it.
        [(1, 6, "list[int]", False), (1, 17, "int", False)],
        [("ys", "list[int]", 1), ("q", "int", 1)],
        0,
    ),
    (
        "an except handler's bound name",
        "def f():\n    try:\n        pass\n    except ValueError as err:\n        return err\n",
        # "    except ValueError as err" ends at column 28. The name is a bare str on the
        # handler node, so this anchor is recovered from the source rather than read off ast.
        [(3, 28, "ValueError", False)],
        [("err", "ValueError", 3)],
        0,
    ),
    (
        "a wrapped return resolves to the innermost enclosing def, not the outer one",
        (
            "def outer():\n"
            "    def inner(\n"
            "        a,\n"
            "    ):\n"
            "        return a\n"
            "    return inner(1)\n"
        ),
        # The closing ')' of inner's wrapped signature lands on line 3, which sits inside
        # both outer's range (0-5) and inner's (1-4). inner's range is smaller, so the
        # return belongs to inner and carries inner's own def line, 1, not outer's, 0.
        [(3, 5, "int", True)],
        [("inner", "int", 1)],
        0,
    ),
]


@pytest.mark.parametrize(
    ("source", "hints", "expected", "drops"),
    [pytest.param(*case[1:], id=case[0]) for case in CASES],
)
def test_resolve_hint_facts(source, hints, expected, drops) -> None:
    assert resolve_hint_facts(source, hints) == (expected, drops)


def test_a_whole_document_resolves_every_declaration_hint() -> None:
    """All four anchor shapes at once, to catch a map that only works in isolation."""
    source = (
        "class Box:\n"
        "    def __init__(self, w):\n"
        "        self.width = w\n"
        "\n"
        "    def area(self, h):\n"
        "        n = self.width * h\n"
        "        return n\n"
    )
    hints = [
        (1, 24, "int", False),  # parameter w
        (2, 18, "int", False),  # attribute width
        (4, 21, "int", True),  # return of area
        (5, 9, "int", False),  # variable n
    ]

    facts, dropped = resolve_hint_facts(source, hints)

    assert dropped == 0
    assert sorted(facts) == sorted(
        [("w", "int", 1), ("width", "int", 2), ("area", "int", 4), ("n", "int", 5)]
    )


def test_malformed_source_drops_every_hint_rather_than_raising() -> None:
    """A file the AST cannot parse yields no maps, so nothing may resolve by accident."""
    facts, dropped = resolve_hint_facts("def f(:\n", [(0, 7, "int", False)])

    assert (facts, dropped) == ([], 1)


class TestAnchorsAgreeWithTheServer:
    """The columns above are hand-computed, so they are also checked against the real thing.

    ``resolve_hint_facts`` inverts an anchor the server chose. A test that only asserts the
    inverse of its own arithmetic would keep passing if both sides drifted together, so these
    two run the server's own hint generator over the same source and resolve what it emits.
    """

    @staticmethod
    def _server_hints(engine, source: str) -> list[tuple[int, int, str, bool]]:
        helper = InlayHintHelper.__new__(InlayHintHelper)  # bypass the @inject constructor
        result = engine.infer_types(source)
        hints = [
            hint
            for scope in result.scope_tree.scopes_by_id.values()
            for hint in helper.generate_hints_for_scope(scope, source)
        ]
        return sorted(_hint_tuples(hints))

    def test_ascii_document_round_trips(self, engine) -> None:
        source = (
            "class Box:\n"
            "    def __init__(self, w):\n"
            "        self.width = 3\n"
            "\n"
            "    def area(self, h):\n"
            "        s = 2\n"
            "        return s + h\n"
        )

        facts, dropped = resolve_hint_facts(source, self._server_hints(engine, source))

        assert dropped == 0
        assert ("width", "int", 2) in facts
        assert ("s", "int", 5) in facts
        assert ("area", "int", 4) in facts

    def test_wrapped_signature_return_round_trips(self, engine) -> None:
        """The server's own ``_signature_end`` anchors this return past the ')' on line 2,
        never on the ``def`` line, which is exactly the case ``resolve_hint_facts`` used to
        drop. Only the real hint generator can prove the anchor lands where the fallback
        expects it to, rather than where hand-computed test columns assume it does."""
        source = "def area(\n    h,\n):\n    s = 2\n    return s + h\n"

        hints = self._server_hints(engine, source)
        assert any(is_return and line0 == 2 for line0, _char, _type_str, is_return in hints), (
            f"expected the server to anchor the return hint on the closing-paren line, got {hints}"
        )

        facts, dropped = resolve_hint_facts(source, hints)

        assert dropped == 0
        assert any(name == "area" and line0 == 0 for name, _type_str, line0 in facts)

    def test_non_ascii_identifiers_round_trip(self, engine) -> None:
        """Every anchor here sits past a multi-byte character, so a byte column would miss."""
        source = "class Bäx:\n    def __init__(self, wïdth):\n        tötal = 3\n"

        facts, dropped = resolve_hint_facts(source, self._server_hints(engine, source))

        assert dropped == 0
        assert ("tötal", "int", 2) in facts

    def test_with_except_and_comprehension_targets_round_trip(self, engine) -> None:
        """The three forms whose hints the inverse mapping used to have no position for.

        Each was drawn by the server and matched nothing here, so it left as a drop rather
        than as a wrong fact, which is why nothing failed while the facts went missing. The
        engine draws all three in one document so a map that only works on one of them is
        not mistaken for a map that works.
        """
        source = (
            "import io\n"
            "\n"
            "\n"
            "def f():\n"
            "    with io.StringIO() as fh:\n"
            "        pass\n"
            "    try:\n"
            "        pass\n"
            "    except ValueError as err:\n"
            "        pass\n"
            "    ys = [q for q in range(3)]\n"
            "    return ys\n"
        )

        facts, dropped = resolve_hint_facts(source, self._server_hints(engine, source))

        assert dropped == 0
        assert ("fh", "_IOBase", 4) in facts
        assert ("err", "ValueError", 8) in facts
        assert ("q", "int", 10) in facts

    def test_starred_parameters_round_trip(self, engine) -> None:
        """``*integers`` and ``**kwargs`` are the two the corpus sweep found still dropping.

        TypeEvalPy's ground truth asks for both by their bare names, and the server infers
        and draws both, so a drop here is recall the scoring never had a chance at.
        """
        source = "def my_sum(a, *integers, **kwargs):\n    return a\n"

        hints = self._server_hints(engine, source)
        facts, dropped = resolve_hint_facts(source, hints)

        assert dropped == 0
        assert any(name == "integers" for name, _type_str, _line0 in facts), (
            f"expected a fact for the starred parameter, got {facts} from {hints}"
        )
        assert any(name == "kwargs" for name, _type_str, _line0 in facts)


class TestExceptHandlerAnchorSpellings:
    """``ExceptHandler.name`` is a ``str``, so its anchor is derived rather than read.

    Every other binding form hands ``_collect_structure`` an ``expr`` with an
    ``end_col_offset`` on it. This one does not, so the column comes from tokenizing the span
    between the end of the exception type and the start of the handler's body. These cases
    are the spellings that span can take, and each column below is the UTF-16 offset just
    past the bound name, which is where the server anchors the hint.
    """

    @staticmethod
    def _resolves(source: str, line0: int, char: int, name: str) -> None:
        assert resolve_hint_facts(source, [(line0, char, "E", False)]) == (
            [(name, "E", line0)],
            0,
        )

    def test_extra_whitespace_around_as(self) -> None:
        source = (
            "def f():\n    try:\n        pass\n"
            "    except ValueError   as    err:\n        return err\n"
        )
        self._resolves(source, 3, 33, "err")

    def test_dotted_exception_type(self) -> None:
        source = (
            "import mod\n\n\ndef f():\n    try:\n        pass\n"
            "    except mod.Err as err:\n        return err\n"
        )
        self._resolves(source, 6, 25, "err")

    def test_parenthesised_tuple_of_exception_types(self) -> None:
        source = (
            "def f():\n    try:\n        pass\n"
            "    except (ValueError, TypeError) as err:\n        return err\n"
        )
        self._resolves(source, 3, 41, "err")

    def test_handler_split_across_a_continuation_line(self) -> None:
        """The bracketed type ends on a later line than the ``except``, so the anchor's line
        is the one the ``as`` sits on rather than the handler's own."""
        source = (
            "def f():\n    try:\n        pass\n"
            "    except (\n        ValueError\n    ) as err:\n        return err\n"
        )
        self._resolves(source, 5, 12, "err")

    def test_backslash_continuation_before_the_as(self) -> None:
        source = (
            "def f():\n    try:\n        pass\n"
            "    except ValueError \\\n            as err:\n        return err\n"
        )
        self._resolves(source, 4, 18, "err")

    def test_except_star_group_handler(self) -> None:
        source = (
            "def f():\n    try:\n        pass\n    except* ValueError as err:\n        return err\n"
        )
        self._resolves(source, 3, 29, "err")

    def test_body_on_the_handler_line(self) -> None:
        """The span ends at the body's first statement, which here starts on the same line."""
        source = "def f():\n    try:\n        pass\n    except ValueError as err: return err\n"
        self._resolves(source, 3, 28, "err")

    def test_non_ascii_bound_name(self) -> None:
        """The tokenizer counts code points, the hint carries UTF-16, and the two agree only
        because the column is converted; the byte offset would be 29."""
        source = (
            "def f():\n    try:\n        pass\n    except ValueError as ërr:\n        return ërr\n"
        )
        self._resolves(source, 3, 28, "ërr")
        assert resolve_hint_facts(source, [(3, 29, "E", False)]) == ([], 1)

    def test_two_handlers_binding_the_same_name_stay_apart(self) -> None:
        """Each handler's span is searched separately, so the inner one cannot borrow the
        outer one's anchor and file a second fact on the wrong line."""
        source = (
            "def f():\n    try:\n        pass\n    except ValueError as err:\n"
            "        try:\n            pass\n        except TypeError as err:\n"
            "            return err\n"
        )

        facts, dropped = resolve_hint_facts(
            source, [(3, 28, "ValueError", False), (6, 31, "TypeError", False)]
        )

        assert dropped == 0
        assert sorted(facts) == [("err", "TypeError", 6), ("err", "ValueError", 3)]

    def test_an_unnamed_handler_contributes_no_anchor(self) -> None:
        """``except ValueError:`` binds nothing, so a hint at the type's own end must drop
        rather than resolve onto the exception class's name."""
        source = "def f():\n    try:\n        pass\n    except ValueError:\n        return 1\n"

        assert resolve_hint_facts(source, [(3, 21, "E", False)]) == ([], 1)


class TestUsageHintsAreDiscriminatedByPosition:
    """A usage hint and a variable declaration hint are character-identical on the wire.

    Both ``_build_type_hint`` (declarations) and ``generate_usage_hints`` (usage sites) render
    ``f"{sep}{type_str}"`` with a one-space separator, so a hint's *label* carries no signal a
    consumer could read. ``resolve_hint_facts`` never looks at the label shape for this. It
    discriminates by position instead, against the Store-target maps ``_collect_structure``
    builds, which only ever contain binding (Store) occurrences — a usage hint sits at a Load
    and matches none of them, so it is dropped exactly like any other unresolvable hint. These
    tests drive that through the real ``InlayHintHelper`` over a live Jedi engine, because a
    hand-built hint tuple can prove the lookup is correct without proving the server's own
    declaration and usage hints actually land where the lookup expects.
    """

    @staticmethod
    def _declaration_hints(helper: InlayHintHelper, source: str, result) -> list:
        return [
            hint
            for scope in result.scope_tree.scopes_by_id.values()
            for hint in helper.generate_hints_for_scope(scope, source)
        ]

    @staticmethod
    def _usage_hints(helper: InlayHintHelper, source: str, result) -> list:
        return asyncio.run(
            helper.process_usage_hints(source, None, 0, len(source.splitlines()), result)
        )

    def test_a_genuine_read_site_shares_the_declarations_label_but_only_the_declaration_resolves(
        self, engine
    ) -> None:
        """``x``'s declaration and its ``return x`` read both render `` int``, live off Jedi.

        ``f`` also gets its own return-type declaration hint here, since it returns the ``int``
        ``x`` — that hint is unrelated to the ambiguity under test and is asserted past rather
        than suppressed, so a future change that dropped it would fail here for the right
        reason instead of silently narrowing what this test covers.
        """
        source = "def f():\n    x = 1\n    return x\n"
        helper = InlayHintHelper(NameCollector(), engine, Settings())
        result = engine.infer_types(source)

        declarations = self._declaration_hints(helper, source, result)
        usages = self._usage_hints(helper, source, result)

        x_declaration = next(h for h in declarations if h.position.line == 1)
        assert x_declaration.label == " int"
        assert usages and usages[0].label == " int"
        assert x_declaration.label == usages[0].label  # identical wire shape, as claimed

        facts, dropped = resolve_hint_facts(source, _hint_tuples(declarations + usages))

        assert ("x", "int", 1) in facts
        assert ("f", "int", 0) in facts
        assert len(facts) == 2  # the usage resolves to no third fact
        assert dropped == 1

    def test_a_self_read_never_lands_on_the_attribute_it_sets(self, engine) -> None:
        """Corroborates the position-disjointness argument on a genuinely mixed statement.

        ``self`` is a *parameter*, not an attribute, so ``get_declaration_positions`` does cover
        its declaration — at the ``def`` line, where the parameter is bound. Reading ``self`` in
        ``self.width = 3`` to set an attribute on it is a separate, later Load occurrence at a
        different ``(line, char)``, which is exactly why ``get_declaration_positions`` (a filter
        keyed on the declaring occurrence's own position, never on later mentions of the same
        name) does not suppress it: nothing needs to, since a usage hint at any position other
        than the declaration's own is legitimate and expected. What has to hold for
        ``resolve_hint_facts`` is that this legitimate, unsuppressed usage hint still cannot be
        mistaken for ``width``'s own attribute declaration on the following line — the two anchor
        different identifiers ending at different columns (``self`` ends before the ``.``,
        ``width`` ends at the statement's end) — and this pins that empirically rather than
        assumes it from reading the AST shapes alone.
        """
        source = "class Box:\n    def __init__(self, w):\n        self.width = 3\n"
        helper = InlayHintHelper(NameCollector(), engine, Settings())
        result = engine.infer_types(source)

        declarations = self._declaration_hints(helper, source, result)
        usages = self._usage_hints(helper, source, result)
        assert declarations and usages, "the scenario stopped exercising both hint kinds"

        decl_positions = {(h.position.line, h.position.character) for h in declarations}
        usage_positions = {(h.position.line, h.position.character) for h in usages}
        assert decl_positions.isdisjoint(usage_positions), (
            f"a usage hint landed on a declaration's own anchor: "
            f"declarations={declarations}, usages={usages}"
        )

        facts, _dropped = resolve_hint_facts(source, _hint_tuples(declarations + usages))
        assert ("width", "int", 2) in facts


def test_padding_distinguishes_declaration_from_usage_on_the_wire_but_is_not_the_mechanism() -> (
    None
):
    """Corroborating canary, not the classification mechanism.

    ``_build_type_hint`` (declarations) emits ``padding_left=False, padding_right=False``;
    ``generate_usage_hints`` (usage sites) emits ``True, True``. Reading that one boolean would
    be less code than the position lookup ``resolve_hint_facts`` actually performs, and the
    lookup deliberately does not read it. Padding is a cosmetic rendering choice, and a harness
    keyed on it would silently misclassify every declaration the moment someone adjusted the
    visual spacing, whereas a hint that matches no Store position is dropped today regardless.
    If this test ever fails, the server's hint rendering changed, and whoever changed it should
    read the reasoning above before touching ``resolve_hint_facts``.
    """
    helper = InlayHintHelper.__new__(InlayHintHelper)  # bypass the @inject constructor

    declaration = helper._build_type_hint(1, 5, " ", "int", True)
    usage = helper.generate_usage_hints(
        [NameLocation(name="x", line=3, col=11, is_definition=False, end_col=12)],
        {(3, 11): "int"},
        set(),
    )[0]

    assert declaration.label == usage.label == " int"
    assert (declaration.padding_left, declaration.padding_right) == (False, False)
    assert (usage.padding_left, usage.padding_right) == (True, True)


def test_a_usage_labelled_hint_scrapes_as_non_return_even_at_a_returns_own_position() -> None:
    """Closes the returns half of the ``get_declaration_positions`` hole at its real mechanism.

    The brief named two gaps in the server's ``get_declaration_positions``, namely
    ``scope.attributes`` and returns. The attributes half is closed by position disjointness
    (see ``TestUsageHintsAreDiscriminatedByPosition``), but a return is never looked up by
    position in the first place -- ``resolve_hint_facts`` routes to its ``is_return`` branch
    purely on a boolean ``_hint_tuples`` (this module's own scraper) decides from the label
    text, specifically whether it starts with ``"->"``. A usage hint's label is always
    ``f" {type_str}"`` (``generate_usage_hints``), which never starts with ``"->"``, so
    ``_hint_tuples`` scrapes ``is_return=False`` for it regardless of position. This constructs
    a raw wire hint with a usage-shaped label sitting at the exact ``(line, character)`` a real
    return hint would use, and pins that it still scrapes as a non-return.
    """
    return_anchor_hint = types.InlayHint(
        position=types.Position(line=0, character=7),
        label=" int",  # a usage/declaration-shaped label, never "-> int"
        kind=types.InlayHintKind.Type,
        padding_left=True,
        padding_right=True,
    )

    (line0, char, type_str, is_return) = _hint_tuples([return_anchor_hint])[0]

    assert (line0, char, type_str) == (0, 7, "int")
    assert is_return is False
