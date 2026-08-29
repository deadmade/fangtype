"""Sync bridge wiring the benchmark runners to the LSP server."""

from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from benchmark.lsp_client.client import FangtypeLspClient
from benchmark.lsp_client.shim import collect_document, insert_document

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Sequence


def bench_cache_home() -> str:
    """The benchmark's mypy cache directory.

    One fixed path, because a run drives exactly one server process. It used to be
    indexed per worker so that concurrent bridges never shared a cache directory, mypy
    having no cross-process cache locking (see ``mypy_runner.py``). With the pool gone
    there is nothing to keep apart, and a stable path keeps the cache warm across runs.
    """
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return str(base / "fangtype-bench" / "bridge")


class ClientBridge:
    """Owns the client on a background event loop; blocks sync callers on its result."""

    def __init__(
        self,
        engine: str = "jedi",
        root_uri: str | None = None,
        timeout: float = 30.0,
        project_root: str | None = None,
        config_overrides: dict[str, Any] | None = None,
    ) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._client = FangtypeLspClient(
            engine=engine,
            root_uri=root_uri,
            timeout=timeout,
            cache_home=bench_cache_home(),
            project_root=project_root,
            config_overrides=config_overrides,
        )
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


def map_over_bridge[T, R](
    items: Sequence[T],
    *,
    make_bridge: Callable[[], ClientBridge],
    fn: Callable[[ClientBridge, T, int], R],
    on_done: Callable[[int, T, R], None] | None = None,
) -> list[R | None]:
    """Run ``fn`` over ``items`` on one server process, in input order.

    This replaces a pool that sharded the corpus across several server subprocesses.
    That pool measured a configuration no user is in, because the shipped server is a
    single long-lived process, and the sharding was not neutral: splitting 143 files
    across eight processes kept each one's parso parse cache below the size at which
    parso starts evicting, which raised the measured match count by roughly 250 targets
    against running them all through one process.

    ``on_done(index, item, result)`` runs as each item finishes, for progress output and
    journal appends. It needs no lock now that nothing is concurrent. The bridge is
    closed even if ``fn`` raises.
    """
    results: list[R | None] = [None] * len(items)
    if not items:
        return results

    bridge = make_bridge()
    try:
        for index, item in enumerate(items):
            result = fn(bridge, item, index)
            results[index] = result
            if on_done is not None:
                on_done(index, item, result)
    finally:
        bridge.close()
    return results
