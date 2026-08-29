"""Two interchangeable ways to strip one corpus file's annotations.

Preparation used to construct a ``RemovalEngine`` and call it in-process, which is the
one place in the harness that reached the server's logic without crossing the protocol
the VS Code client crosses. The stripped corpus is the ground truth every mypy-corpus
number is scored against, so a bug that lives in the transport -- a wire shape the
harness reads differently from the extension, a handler that silently swallows an
exception -- was invisible to the evaluation by construction.

``LspRemovalSource`` closes that gap by issuing the same two requests, with the same
parameter vectors, in the same order as ``removeCommands.ts``'s
``removeAllTypesInFile``. ``InProcessRemovalSource`` keeps the old path available, both
for the tests that are about caching and manifest shape rather than transport and for
the byte-identity comparison that proves the two agree on the real corpus.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from benchmark.lsp_client.label_parse import _field, as_mapping, modified_source_from_edit
from fangtype.removal import RemovalEngine

if TYPE_CHECKING:
    from benchmark.lsp_client.factory import ClientBridge


class RemovalSource(Protocol):
    """Strips every annotation from one file and reports what it removed.

    ``strip`` returns the stripped text plus one record per removed annotation, already
    normalised to a plain mapping so a caller's ``entry["type"]`` read works the same
    whether the record came from the engine directly or off the wire.
    """

    def strip(self, uri: str, source: str) -> tuple[str, list[dict[str, Any]]]:
        """Return ``(stripped_source, removal_records)`` for the file at ``uri``."""
        ...


@runtime_checkable
class ClosableRemovalSource(Protocol):
    """A removal source that owns a resource, such as a server subprocess.

    Split out rather than folded into ``RemovalSource`` because only the owner of a
    source may close it. ``prepare_mypy_workspace`` closes the source it built itself
    and leaves a caller-supplied one alone, and this protocol is what lets it make that
    distinction without an untyped ``getattr``.
    """

    def close(self) -> None:
        """Release whatever this source owns."""
        ...


class InProcessRemovalSource:
    """Calls ``RemovalEngine`` directly, crossing no protocol.

    This is what preparation did before the LSP route existed. It survives for the tests
    that drive ``prepare_mypy_workspace`` over a two-file fixture -- twenty-six calls
    that would otherwise each spawn a server subprocess -- and for the comparison test
    that runs the corpus through both sources and asserts the stripped trees are
    byte-identical.
    """

    def strip(self, uri: str, source: str) -> tuple[str, list[dict[str, Any]]]:
        """Strip ``source``; ``uri`` is ignored, since nothing here reads from disk."""
        stripped_source, summary = RemovalEngine().remove_types(
            source,
            variables=None,
            include_functions=True,
        )
        return stripped_source, [as_mapping(entry) for entry in summary["will_remove"]]


class LspRemovalSource:
    """Strips a file the way the extension does, over two custom requests.

    ``removeCommands.ts:removeAllTypesInFile`` sends ``fangtype/previewRemovals`` with
    ``[uri, null, true]``, returns early when the preview reports no changes, and only
    then sends ``fangtype/removeTypesInFile`` with the same vector. The early return is
    not an optimisation: ``removeTypesInFile`` answers ``success: False`` and carries no
    edit for a file with nothing to remove, so a source that skipped the preview would
    have no stripped text to write for the nine unannotated files in the mypy corpus.

    No ``didOpen`` is sent. Both handlers reach ``ls.workspace.get_text_document(uri)``,
    which reads from disk for a URI the client never opened, and preparation's URIs point
    at files whose on-disk bytes are exactly the source it read. Opening each file would
    additionally cost one full mypy run per file, because ``did_open`` awaits
    ``_run_diagnostics_for_uri``.
    """

    def __init__(self, bridge: ClientBridge) -> None:
        self._bridge = bridge

    def strip(self, uri: str, source: str) -> tuple[str, list[dict[str, Any]]]:
        """Run the client's preview-then-remove sequence against the server.

        Raises rather than degrading when the server answers a shape this cannot read.
        A preparation that swallowed such a failure would write an empty manifest, stamp
        it, and then serve that empty ground truth to every later run from cache.
        """
        preview = self._bridge.run_sync(self._bridge.client.preview_removals(uri))
        self._reject_handler_error(uri, preview)

        # The client's own early return. ``total_changes`` is the engine's
        # ``removed_count``, so this is exactly "the file carried no annotations".
        if not _field(preview, "success") or not _field(preview, "total_changes"):
            return source, []

        records = [as_mapping(entry) for entry in _field(preview, "will_remove") or []]

        response = self._bridge.run_sync(self._bridge.client.remove_types_in_file(uri))
        stripped_source = modified_source_from_edit(response, uri)
        if stripped_source is None:
            message = _field(response, "message")
            raise RuntimeError(
                f"fangtype/removeTypesInFile returned no edit for {uri} after a preview "
                f"reporting {len(records)} removal(s); server message: {message!r}"
            )
        return stripped_source, records

    @staticmethod
    def _reject_handler_error(uri: str, preview: Any) -> None:
        """Turn the preview handler's exception branch back into an exception here.

        ``preview_removals`` answers ``success: False`` for two unrelated reasons. A file
        with nothing to remove is one, because the summary's ``success`` is
        ``removed_count > 0``. The handler catching an exception -- an unparseable file,
        say -- is the other, and that one used to propagate out of ``RemovalEngine`` and
        land the file in ``preparation_error``. Only the error branch attaches a
        ``message``, so its presence is what tells the two apart, and without this check
        a corpus file the server cannot parse would be silently recorded as unannotated.
        """
        message = _field(preview, "message")
        if not _field(preview, "success") and message is not None:
            raise RuntimeError(f"fangtype/previewRemovals failed for {uri}: {message}")

    def close(self) -> None:
        """Shut the bridge, and with it the server subprocess it started."""
        self._bridge.close()
