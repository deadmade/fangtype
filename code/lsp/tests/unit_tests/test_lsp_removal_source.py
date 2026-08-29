"""The LSP removal source must fail loudly on every shape it cannot read.

``prepare_mypy_workspace`` records a file the removal source could not strip with a
``preparation_error`` and refuses to stamp the tree once enough of them accumulate, so a
raise here is what keeps a broken transport out of the cache. A silent degrade is worse
than an exception: it writes the unstripped source into ``stripped/`` with an empty target
list beside it, leaves ``error_file_count`` at zero so the stamp is granted, and every run
afterwards scores against that emptied ground truth without anything having failed.

The one shape that must *not* raise is a preview reporting zero changes. That is the nine
unannotated files of the mypy corpus, whose stripped text is the source verbatim.
"""

from __future__ import annotations

from collections import namedtuple

import pytest

from benchmark.mypy_eval.removal_source import LspRemovalSource

SOURCE = "def g(z):\n    return z\n"
STRIPPED = "def g(z):\n    return z\n"
URI = "file:///corpus/mod.py"


class _FakeBridge:
    """Stands in for ``ClientBridge``, answering canned responses in call order.

    ``run_sync`` is handed whatever ``client.preview_removals`` / ``remove_types_in_file``
    returned, so those are plain functions here rather than coroutines and ``run_sync``
    is the identity. That is enough, because ``LspRemovalSource`` only ever reads fields
    off what comes back.
    """

    def __init__(self, preview: object, removal: object = None) -> None:
        self._preview = preview
        self._removal = removal
        self.calls: list[str] = []
        self.client = self

    def run_sync(self, result: object) -> object:
        return result

    def preview_removals(self, uri: str) -> object:
        self.calls.append("preview")
        return self._preview

    def remove_types_in_file(self, uri: str) -> object:
        self.calls.append("remove")
        return self._removal


def _workspace_edit(uri: str, new_text: str) -> dict[str, object]:
    return {
        "success": True,
        "edits": {
            "documentChanges": [
                {
                    "textDocument": {"uri": uri, "version": None},
                    "edits": [{"newText": new_text}],
                }
            ]
        },
    }


class TestEarlyReturn:
    """A file with nothing to remove costs one request, and keeps its source verbatim."""

    def test_zero_changes_returns_the_source_and_sends_no_second_request(self) -> None:
        bridge = _FakeBridge({"success": False, "total_changes": 0, "will_remove": []})
        source = LspRemovalSource(bridge)  # type: ignore[arg-type]

        stripped, records = source.strip(URI, SOURCE)

        assert stripped is SOURCE
        assert records == []
        assert bridge.calls == ["preview"]

    def test_zero_changes_is_recognised_through_the_pygls_namedtuple_shape(self) -> None:
        """A live response arrives structured as a namedtuple, not a dict."""
        Object = namedtuple("Object", ["success", "total_changes", "will_remove"])
        bridge = _FakeBridge(Object(False, 0, []))
        source = LspRemovalSource(bridge)  # type: ignore[arg-type]

        stripped, records = source.strip(URI, SOURCE)

        assert stripped is SOURCE
        assert records == []
        assert bridge.calls == ["preview"]


class TestRaisesRatherThanDegrading:
    """Every unreadable shape has to reach ``prepare``'s per-file except, not the manifest."""

    def test_handler_error_raises_rather_than_reading_as_unannotated(self) -> None:
        """``success: False`` with a message is the handler's own except branch.

        The engine's ``success`` is ``removed_count > 0``, so a file with nothing to
        remove answers ``False`` too. Only the error branch attaches a message, and
        without telling the two apart an unparseable corpus file would be recorded as
        having carried no annotations.
        """
        bridge = _FakeBridge(
            {
                "success": False,
                "total_changes": 0,
                "will_remove": [],
                "message": "Internal error: cannot parse",
            }
        )
        source = LspRemovalSource(bridge)  # type: ignore[arg-type]

        with pytest.raises(RuntimeError, match="previewRemovals failed"):
            source.strip(URI, SOURCE)

        assert bridge.calls == ["preview"]

    @pytest.mark.parametrize(
        "preview, expected",
        [
            ({"total_changes": 0, "will_remove": []}, "success"),
            ({"success": False, "will_remove": []}, "total_changes"),
            ({"success": True, "total_changes": 1}, "will_remove"),
            ({"will_remove": []}, "success and total_changes"),
            ({}, "success and total_changes and will_remove"),
        ],
        ids=[
            "no_success",
            "no_total_changes",
            "no_will_remove",
            "neither_success_nor_total_changes",
            "none_of_the_three",
        ],
    )
    def test_a_missing_preview_field_raises(
        self, preview: dict[str, object], expected: str
    ) -> None:
        """An absent field reads as ``None``, which is falsey and would take the early return.

        That is the silent path: the file lands in the manifest as unannotated, the error
        count stays zero, the stamp is written, and the emptied ground truth is reused.

        ``will_remove`` fails a step later and just as quietly. The early return is not
        taken, because ``total_changes`` is positive, so the file is stripped correctly and
        gets an empty target list beside it -- a hole in the ground truth with nothing
        recorded as having gone wrong.
        """
        bridge = _FakeBridge(preview)
        source = LspRemovalSource(bridge)  # type: ignore[arg-type]

        with pytest.raises(RuntimeError, match=f"answered without {expected}"):
            source.strip(URI, SOURCE)

        assert bridge.calls == ["preview"]

    def test_a_present_but_empty_will_remove_is_not_a_missing_field(self) -> None:
        """The nine unannotated corpus files answer exactly this, and must not raise."""
        bridge = _FakeBridge({"success": False, "total_changes": 0, "will_remove": []})
        source = LspRemovalSource(bridge)  # type: ignore[arg-type]

        assert source.strip(URI, SOURCE) == (SOURCE, [])

    def test_no_edit_after_a_positive_preview_raises(self) -> None:
        """The preview promised removals, so an answer carrying no edit is a failure."""
        bridge = _FakeBridge(
            {
                "success": True,
                "total_changes": 1,
                "will_remove": [{"variable": "z", "type": "int", "line": 1}],
            },
            {"success": False, "message": "Internal error: gone"},
        )
        source = LspRemovalSource(bridge)  # type: ignore[arg-type]

        with pytest.raises(RuntimeError, match="returned no edit"):
            source.strip(URI, SOURCE)

        assert bridge.calls == ["preview", "remove"]


class TestHappyPath:
    """A preview reporting removals is followed by the remove request, and its edit is read."""

    def test_records_come_from_the_preview_and_text_from_the_edit(self) -> None:
        record = {"variable": "z", "type": "int", "line": 1, "target_kind": "function_param"}
        bridge = _FakeBridge(
            {"success": True, "total_changes": 1, "will_remove": [record]},
            _workspace_edit(URI, STRIPPED),
        )
        source = LspRemovalSource(bridge)  # type: ignore[arg-type]

        stripped, records = source.strip(URI, SOURCE)

        assert stripped == STRIPPED
        assert records == [record]
        assert bridge.calls == ["preview", "remove"]
