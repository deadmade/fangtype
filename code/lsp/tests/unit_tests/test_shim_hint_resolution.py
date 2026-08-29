"""Tests for ``resolve_hint_facts`` in benchmark/lsp_client/shim.py.

Inlay hints are position-keyed and the runners score name-keyed facts, so the whole
benchmark's ability to read inference off the channel the extension actually uses rests on
inverting a hint's anchor back to the binding it annotates. Every case below pins one
anchor shape, and the two non-ASCII cases pin the byte→code-point→UTF-16 conversion, which
no file in either corpus exercises today.
"""

import pytest

from benchmark.lsp_client.shim import _hint_tuples, resolve_hint_facts
from fangtype.utils.inlay_hint_helper import InlayHintHelper

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
        "a return on a wrapped signature is left for later",
        "def f(\n    a,\n):\n    return 1\n",
        # The anchor lands just past the ')' on line 2, which is not a def line.
        [(2, 1, "int", True)],
        [],
        1,
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

    def test_non_ascii_identifiers_round_trip(self, engine) -> None:
        """Every anchor here sits past a multi-byte character, so a byte column would miss."""
        source = "class Bäx:\n    def __init__(self, wïdth):\n        tötal = 3\n"

        facts, dropped = resolve_hint_facts(source, self._server_hints(engine, source))

        assert dropped == 0
        assert ("tötal", "int", 2) in facts
