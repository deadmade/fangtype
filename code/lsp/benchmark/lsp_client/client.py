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

_BENCH_CONFIG: dict[str, Any] = {
    "mypy_inference_validation_enabled": False,
    "mypy_enabled": False,
}

_DEFAULT_TIMEOUT = 30.0


def _bench_configuration_params() -> types.DidChangeConfigurationParams:
    """Build the ``workspace/didChangeConfiguration`` params that push the
    benchmark settings to the server.
    """
    settings: dict[str, dict[str, Any]] = {"fangtype": dict(_BENCH_CONFIG)}
    return types.DidChangeConfigurationParams(settings=settings)


class FangtypeLspClient:
    """Owns one fangtype-server subprocess and exposes typed request helpers."""

    def __init__(
        self,
        engine: str = "jedi",
        root_uri: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._engine = engine
        self._root_uri = root_uri
        self._timeout = timeout
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

        await self._client.start_io(
            sys.executable, "-m", "fangtype.server", env=env, start_new_session=True
        )
        await asyncio.wait_for(
            self._client.initialize_async(
                types.InitializeParams(
                    capabilities=types.ClientCapabilities(),
                    root_uri=self._root_uri,
                )
            ),
            timeout=self._timeout,
        )
        self._client.initialized(types.InitializedParams())

        self._client.workspace_did_change_configuration(_bench_configuration_params())

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

    async def preview_inserts(self, uri: str) -> Any:
        return await self._custom("fangtype/previewInserts", [uri])

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
