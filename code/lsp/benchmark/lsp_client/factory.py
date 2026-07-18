"""Sync bridge wiring the benchmark runners to the LSP server."""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING, Any

from benchmark.lsp_client.client import FangtypeLspClient
from benchmark.lsp_client.shim import collect_document, insert_document

if TYPE_CHECKING:
    from collections.abc import Coroutine


class ClientBridge:
    """Owns the client on a background event loop; blocks sync callers on its result."""

    def __init__(
        self,
        engine: str = "jedi",
        root_uri: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._client = FangtypeLspClient(engine=engine, root_uri=root_uri, timeout=timeout)
        self._cache: dict[tuple[str, str], tuple[list, list]] = {}
        self.run_sync(self._client.start())

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    @property
    def client(self) -> FangtypeLspClient:
        return self._client

    def run_sync(self, coro: Coroutine[Any, Any, Any]) -> Any:
        """Run a coroutine on the background loop, blocking the caller for its result."""
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def collect_sync(self, uri: str, source: str, did_open: bool = False) -> tuple[list, list]:
        """Fetch (inlay hints, previewInserts) for a document, cached per (uri, source)."""
        key = (uri, source)
        if key not in self._cache:
            self._cache[key] = self.run_sync(
                collect_document(self._client, uri, source, did_open=did_open)
            )
        return self._cache[key]

    def insert_sync(self, uri: str, source: str) -> tuple[bool, str | None, dict[str, int]]:
        """Insert all inferred types into ``source`` (opened as ``uri``), return
        (success, modified_source, variable_drop_reasons). Not cached -- insertion is a
        mutation, not a pure read."""
        return self.run_sync(insert_document(self._client, uri, source))

    def close(self) -> None:
        try:
            self.run_sync(self._client.stop())
        finally:
            self._loop.call_soon_threadsafe(self._cancel_and_stop)
            self._thread.join(timeout=5)

    def _cancel_and_stop(self) -> None:
        for task in asyncio.all_tasks(self._loop):
            task.cancel()
        self._loop.stop()
