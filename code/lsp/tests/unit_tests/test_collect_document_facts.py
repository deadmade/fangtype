"""Tests for ``collect_document``/``ClientBridge.collect_sync`` after the fact source moved.

The harness used to score inference from ``fangtype/previewInserts``, a custom request the
shipped extension never sends and this harness was the only caller of. ``collect_document``
now asks for inlay hints alone and resolves the name-keyed facts out of them, so the
benchmark measures the channel a developer is actually served by. These tests pin the three
things that move with that: no ``previewInserts`` call goes out, the ``did_open`` protocol is
unchanged, and the drop count ``resolve_hint_facts`` reports does not vanish on the way back.
"""

import asyncio
from collections.abc import Coroutine
from typing import TYPE_CHECKING, Any, cast

import pytest
from lsprotocol import types

from benchmark.lsp_client.factory import ClientBridge
from benchmark.lsp_client.shim import collect_document
from fangtype.utils.inlay_hint_helper import InlayHintHelper

if TYPE_CHECKING:
    from benchmark.lsp_client.client import FangtypeLspClient

URI = "file:///corpus/mod.py"


def _hint(line: int, character: int, label: str) -> types.InlayHint:
    return types.InlayHint(
        position=types.Position(line=line, character=character),
        label=label,
        kind=types.InlayHintKind.Type,
    )


class _FakeClient:
    """Records the calls ``collect_document`` makes and answers with canned hints.

    ``preview_inserts`` is deliberately present and raises. A fake that simply omitted the
    method would fail with ``AttributeError`` too, but for the wrong reason, and would keep
    passing if someone reintroduced the call through a differently named helper.
    """

    def __init__(self, hints: list[types.InlayHint]) -> None:
        self._hints = hints
        self.calls: list[str] = []

    async def open_document(self, uri: str, source: str) -> None:
        self.calls.append("open")

    async def close_document(self, uri: str) -> None:
        self.calls.append("close")

    async def inlay_hints(self, uri: str) -> list[types.InlayHint]:
        self.calls.append("hints")
        return self._hints

    async def preview_inserts(self, uri: str) -> object:
        raise AssertionError("collect_document must not send fangtype/previewInserts any more")


class _StubBridge(ClientBridge):
    """A ``ClientBridge`` with the server subprocess and the background loop left out.

    The real ``__init__`` spawns a server and starts an event-loop thread, neither of which a
    counter test needs. Everything ``collect_sync`` reaches is set up here instead, and
    ``run_sync`` drives the coroutine on the calling thread, so the accumulation path under
    test is the production one rather than a reimplementation of it.
    """

    def __init__(self, client: _FakeClient) -> None:
        self._cache = {}
        self.dropped_hints = 0
        self._client = cast("FangtypeLspClient", client)

    def run_sync(self, coro: Coroutine[Any, Any, Any]) -> Any:
        return asyncio.run(coro)


def test_facts_come_from_the_hints_and_no_preview_request_goes_out() -> None:
    """One request, and both halves of the tuple derived from its answer."""
    source = "def f(a):\n    x = 1\n    return x\n"
    client = _FakeClient([_hint(0, 7, " int"), _hint(1, 5, " int"), _hint(0, 8, " -> int")])

    hints, facts = asyncio.run(collect_document(client, URI, source))

    assert client.calls == ["hints"]
    assert hints == [(0, 7, "int", False), (1, 5, "int", False), (0, 8, "int", True)]
    assert sorted(facts) == sorted([("a", "int", 0), ("x", "int", 1), ("f", "int", 0)])


@pytest.mark.parametrize(
    ("did_open", "expected_calls"),
    [
        pytest.param(False, ["hints"], id="inference arm reads the file from disk"),
        pytest.param(True, ["open", "hints", "close"], id="mypy arms sync the text"),
    ],
)
def test_did_open_still_decides_whether_the_text_is_synced(did_open, expected_calls) -> None:
    """The one behaviour the fact-source swap was not allowed to disturb.

    With ``did_open`` False the on-disk file already holds the exact source, so ``didOpen``
    is skipped to keep the per-open diagnostics scheduling from congesting a long run. With
    it True the URI points at an annotated original while ``source`` is the stripped text,
    so the text has to be synced or the server would infer over the wrong document.
    """
    client = _FakeClient([_hint(1, 5, " int")])

    asyncio.run(collect_document(client, URI, "def f():\n    x = 1\n", did_open=did_open))

    assert client.calls == expected_calls


def test_the_document_is_closed_even_when_the_hint_request_fails() -> None:
    """A synced document that is never closed leaks the stripped text into every later read."""

    class _FailingClient(_FakeClient):
        async def inlay_hints(self, uri: str) -> list[types.InlayHint]:
            self.calls.append("hints")
            raise RuntimeError("timeout")

    client = _FailingClient([])

    with pytest.raises(RuntimeError):
        asyncio.run(collect_document(client, URI, "x = 1\n", did_open=True))

    assert client.calls == ["open", "hints", "close"]


class TestTheDropCountSurvivesTheTwoElementReturn:
    """``resolve_hint_facts`` returns ``(facts, dropped)`` so drops are a value, not a log line.

    ``collect_document`` cannot widen its return to carry ``dropped`` along, because four
    runners plus the bridge's cache unpack a two-element tuple. Wiring the two together
    naively would therefore drop the count on the floor and quietly undo the property it was
    built for. These pin the two routes it leaves by instead.
    """

    @staticmethod
    def _usage_hint_source() -> tuple[str, list[types.InlayHint]]:
        """A declaration hint plus a usage hint, which sits at a Load and resolves to nothing."""
        source = "def f():\n    x = 1\n    return x\n"
        return source, [_hint(1, 5, " int"), _hint(2, 12, " int")]

    def test_on_dropped_receives_the_count(self) -> None:
        source, hints = self._usage_hint_source()
        seen: list[int] = []

        _hints, facts = asyncio.run(
            collect_document(_FakeClient(hints), URI, source, on_dropped=seen.append)
        )

        assert facts == [("x", "int", 1)]
        assert seen == [1]

    def test_on_dropped_is_called_even_when_nothing_dropped(self) -> None:
        """The total is a sum over every document collected, not over the lossy subset."""
        seen: list[int] = []

        asyncio.run(
            collect_document(
                _FakeClient([_hint(1, 5, " int")]),
                URI,
                "def f():\n    x = 1\n",
                on_dropped=seen.append,
            )
        )

        assert seen == [0]

    def test_the_bridge_total_moves_when_a_document_drops_a_hint(self) -> None:
        """``ClientBridge.dropped_hints`` is what a runner reads once at the end of a run."""
        source, hints = self._usage_hint_source()
        bridge = _StubBridge(_FakeClient(hints))

        _hints, facts = bridge.collect_sync(URI, source)

        assert facts == [("x", "int", 1)]
        assert bridge.dropped_hints == 1

    def test_a_cached_document_does_not_count_its_drops_twice(self) -> None:
        """The second read never reaches the server, so it must not reach the counter either."""
        source, hints = self._usage_hint_source()
        bridge = _StubBridge(_FakeClient(hints))

        first = bridge.collect_sync(URI, source)
        second = bridge.collect_sync(URI, source)

        assert first == second
        assert bridge.dropped_hints == 1


def test_a_name_bound_twice_in_one_scope_yields_exactly_one_fact(engine) -> None:
    """TEMPORARY PIN — a later task inverts this assertion, and that will not be a regression.

    ``Scope.variables`` is a property returning ``types[-1]`` per name, so the server emits
    one declaration hint per name per scope, anchored at the last binding and carrying that
    binding's type. ``previewInserts`` reported every binding, so moving the harness onto
    hints loses the earlier ones. That loss is real and is recorded here rather than left to
    surface later as unexplained drift in an evaluation number.

    A later task changes the server to emit one hint per binding. When it lands, this file
    stops describing the tool and the assertion below flips to two facts. Whoever does that
    should delete this docstring with it, so that nobody reads the inversion as a regression
    and nobody reads today's behaviour as intended.

    The hints come from the real ``InlayHintHelper`` over a live engine on purpose. A
    hand-built pair of hint tuples would resolve to two facts quite happily, so it would pin
    ``resolve_hint_facts`` rather than the server behaviour that is actually under test.
    """
    source = "def f():\n    x = 1\n    x = 2\n    return x\n"
    helper = InlayHintHelper.__new__(InlayHintHelper)  # bypass the @inject constructor
    result = engine.infer_types(source)
    hints = [
        hint
        for scope in result.scope_tree.scopes_by_id.values()
        for hint in helper.generate_hints_for_scope(scope, source)
    ]

    _hints, facts = asyncio.run(collect_document(_FakeClient(hints), URI, source))

    variable_facts = [fact for fact in facts if fact[0] == "x"]
    assert variable_facts == [("x", "int", 2)], (
        "the server now emits a hint per binding rather than per name — see this test's "
        "docstring before treating the extra fact as a failure"
    )
