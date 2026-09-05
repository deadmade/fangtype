from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import sys
from pathlib import Path
from typing import Any

from lsprotocol import types
from pygls.lsp.client import LanguageClient

# code/lsp/src — the server subprocess needs this on PYTHONPATH since the package
# isn't pip-installed in the dev env. lsp_client/ -> benchmark/ -> code/lsp/.
_SRC_DIR = str(Path(__file__).resolve().parents[2] / "src")

# The shipped defaults, so a run measures the pipeline the tool actually ships. `mypy_enabled`
# gates the insert-path assignability gate and defaults to True; turning it off made the gate a
# no-op on every benchmark file and `all_mypy_invalid` structurally zero, which characterises a
# configuration no user runs. `set_mypy_gate` lets a caller put the gate back to off deliberately.
_BENCH_CONFIG: dict[str, Any] = {
    "mypy_enabled": True,
}


def set_mypy_gate(enabled: bool) -> None:
    """Turn the insert-path assignability gate on or off for every client built afterwards."""
    _BENCH_CONFIG["mypy_enabled"] = enabled


_DEFAULT_TIMEOUT = 30.0


def _bench_configuration_params(
    overrides: dict[str, Any] | None = None,
) -> types.DidChangeConfigurationParams:
    """Build the ``workspace/didChangeConfiguration`` params that push the
    benchmark settings to the server.

    ``overrides`` applies to this one client rather than to every client built
    afterwards, which is what ``set_mypy_gate`` above does. A caller that needs a
    server configured differently from the run's own configuration -- the corpus
    preparation bridge, which strips annotations and never inserts one, so the
    assignability gate is dead weight it would pay a full mypy run per file for --
    passes it here instead of reaching for the module-level default, whose mutation
    would leak into every bridge the same process builds later.
    """
    settings: dict[str, dict[str, Any]] = {"fangtype": {**_BENCH_CONFIG, **(overrides or {})}}
    return types.DidChangeConfigurationParams(settings=settings)


class FangtypeLspClient:
    """Owns one fangtype-server subprocess and exposes typed request helpers."""

    def __init__(
        self,
        engine: str = "jedi",
        root_uri: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        cache_home: str | None = None,
        project_root: str | None = None,
        config_overrides: dict[str, Any] | None = None,
    ) -> None:
        self._engine = engine
        self._root_uri = root_uri
        # Sent as ``initializationOptions.projectRoot``, which the server hands to Jedi as
        # an explicit project root. Without it Jedi walks up from the document for a
        # pyproject.toml, and for a corpus prepared under code/lsp/benchmark/tmp/ that walk
        # finds code/lsp's own pyproject and makes Fangtype the project. The corpus package
        # then resolves through site-packages instead of the prepared tree, which for the
        # cold-start arm would silently score against the installed, mypyc-compiled mypy.
        self._project_root = project_root
        self._timeout = timeout
        # Overrides XDG_CACHE_HOME for this server subprocess only; see pool.py for why.
        self._cache_home = cache_home
        # Per-client settings, layered over ``_BENCH_CONFIG`` at handshake time. Copied so a
        # caller's dict cannot mutate this client's configuration after the push.
        self._config_overrides = dict(config_overrides or {})
        self._client = LanguageClient("fangtype-bench", "v1")
        self._docs: dict[str, int] = {}  # uri -> line count (for inlay ranges)
        self._stderr_task: asyncio.Task[None] | None = None
        self._register_responders()

    def _register_responders(self) -> None:
        """Register server->client handlers BEFORE the handshake."""

        @self._client.feature(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)
        def _diagnostics(_params: types.PublishDiagnosticsParams) -> None:
            return None

    async def start(self) -> None:
        existing_path = os.environ.get("PYTHONPATH", "")
        pythonpath = _SRC_DIR + (os.pathsep + existing_path if existing_path else "")
        env = {**os.environ, "FANGTYPE_ENGINE": self._engine, "PYTHONPATH": pythonpath}
        if self._cache_home is not None:
            # mypy has no cross-process cache locking (mypy_runner.py); a distinct
            # XDG_CACHE_HOME keeps this server's mypy cache dir out of every other bridge's way.
            # This relocates the *whole* subprocess's cache root, not only mypy's -- parso's
            # own cache (parso.cache._get_default_cache_path) reads the same variable, so each
            # bridge also gets a cold, isolated parso/Jedi cache. That plausibly touches the
            # inference-drift candidates sec:eval-threats names, but is not established to fix
            # them, and it means a benchmark run using this is no longer cache-comparable with
            # runs recorded before this change.
            env["XDG_CACHE_HOME"] = self._cache_home

        await self._client.start_io(
            sys.executable, "-m", "fangtype.server", env=env, start_new_session=True
        )
        await asyncio.wait_for(
            self._client.initialize_async(
                types.InitializeParams(
                    capabilities=types.ClientCapabilities(),
                    root_uri=self._root_uri,
                    initialization_options=(
                        {"projectRoot": self._project_root}
                        if self._project_root is not None
                        else None
                    ),
                )
            ),
            timeout=self._timeout,
        )
        self._client.initialized(types.InitializedParams())

        self._client.workspace_did_change_configuration(
            _bench_configuration_params(self._config_overrides)
        )

        self._stderr_task = asyncio.create_task(self._drain_stderr())

    async def _drain_stderr(self) -> None:
        """Continuously read the server's stderr and echo it to our own stderr."""
        server = getattr(self._client, "_server", None)
        stderr = getattr(server, "stderr", None)
        if stderr is None:
            return
        try:
            while True:
                line = await stderr.readline()
                if not line:
                    break
                sys.stderr.buffer.write(b"[server] " + line)
                sys.stderr.buffer.flush()
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def open_document(self, uri: str, text: str) -> None:
        self._docs[uri] = len(text.splitlines())
        self._client.text_document_did_open(
            types.DidOpenTextDocumentParams(
                text_document=types.TextDocumentItem(
                    uri=uri, language_id="python", version=1, text=text
                )
            )
        )

    async def close_document(self, uri: str) -> None:
        self._docs.pop(uri, None)
        self._client.text_document_did_close(
            types.DidCloseTextDocumentParams(text_document=types.TextDocumentIdentifier(uri=uri))
        )

    async def inlay_hints(self, uri: str) -> list[types.InlayHint]:
        end_line = self._docs.get(uri, 0) + 1
        result = await asyncio.wait_for(
            self._client.text_document_inlay_hint_async(
                types.InlayHintParams(
                    text_document=types.TextDocumentIdentifier(uri=uri),
                    range=types.Range(
                        start=types.Position(line=0, character=0),
                        end=types.Position(line=end_line, character=0),
                    ),
                )
            ),
            timeout=self._timeout,
        )
        return list(result or [])

    async def insert_types_in_file(self, uri: str) -> Any:
        return await self._custom("fangtype/insertTypesInFile", [uri])

    async def preview_removals(self, uri: str) -> Any:
        """Ask what a whole-file removal would take out, sending the extension's own vector.

        ``[uri, None, True]`` is ``removeCommands.ts:91`` verbatim, namely no variable
        filter and function annotations included. The parameters decide what counts as a
        removable target, so a harness that guessed at them would score against a ground
        truth no user ever gets.
        """
        return await self._custom("fangtype/previewRemovals", [uri, None, True])

    async def remove_types_in_file(self, uri: str) -> Any:
        """Remove every annotation in the file, sending the extension's own vector.

        ``[uri, None, True]`` is ``removeCommands.ts:134`` verbatim. The response carries
        the stripped text as a single full-document ``TextEdit``; see
        ``modified_source_from_edit``.
        """
        return await self._custom("fangtype/removeTypesInFile", [uri, None, True])

    async def _custom(self, method: str, params: list[Any]) -> Any:
        return await asyncio.wait_for(
            self._client.protocol.send_request_async(method, params),
            timeout=self._timeout,
        )

    async def stop(self) -> None:
        proc = getattr(self._client, "_server", None)
        if self._stderr_task is not None:
            self._stderr_task.cancel()
            self._stderr_task = None
        try:
            await asyncio.wait_for(self._client.shutdown_async(None), timeout=5.0)
            self._client.exit(None)
        except (TimeoutError, Exception):
            pass

        with contextlib.suppress(TimeoutError, Exception):
            await asyncio.wait_for(
                self._client.stop(),  # type: ignore[no-untyped-call]  # pygls stop() is untyped
                timeout=5.0,
            )

        pid = getattr(proc, "pid", None)
        if pid is not None:
            with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
                os.killpg(os.getpgid(pid), signal.SIGKILL)
