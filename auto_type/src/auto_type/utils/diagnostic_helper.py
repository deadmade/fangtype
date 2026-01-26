import asyncio
import logging

from injector import inject
from lsprotocol import types
from pygls.lsp.server import LanguageServer

from auto_type.protocols import DiagnosticEngineProtocol

logger = logging.getLogger(__name__)


class DiagnosticHelper:
    """Helper class for managing and running diagnostics.

    All diagnostic methods are async to work with async engines.
    """

    @inject
    def __init__(self, diagnostic_engine: DiagnosticEngineProtocol) -> None:
        self._timers: dict[str, asyncio.TimerHandle] = {}
        self.diagnostic_engine = diagnostic_engine

    async def run_diagnostics(self, ls: LanguageServer, uri: str, source: str) -> None:
        """Generate and publish diagnostics for a document.

        Args:
            ls: The language server instance
            uri: Document URI
            source: Document source code
        """
        try:
            # Generate diagnostics using async engine
            diagnostics = await self.diagnostic_engine.generate_diagnostics(source, uri)
            logger.info(f"Publishing {len(diagnostics)} diagnostics for {uri}")
            ls.text_document_publish_diagnostics(
                types.PublishDiagnosticsParams(uri=uri, diagnostics=diagnostics)
            )
        except Exception as e:
            # Log error but don't crash server
            logger.error(f"Error running diagnostics: {e}", exc_info=True)
            ls.text_document_publish_diagnostics(
                types.PublishDiagnosticsParams(uri=uri, diagnostics=[])
            )  # Clear diagnostics on error

    def schedule_diagnostics(self, ls: LanguageServer, uri: str) -> None:
        """Schedule debounced diagnostics for a document.

        Args:
            ls: The language server instance
            uri: Document URI
        """
        # Cancel previous timer for this document
        if uri in self._timers:
            self._timers[uri].cancel()

        # Schedule diagnostics after 500ms delay (debounced)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # Fallback for when called from a thread
            loop = asyncio.get_event_loop()

        timer = loop.call_later(
            0.5,  # 500ms debounce
            lambda: asyncio.run_coroutine_threadsafe(self._run_diagnostics_async(ls, uri), loop),
        )
        self._timers[uri] = timer

    async def _run_diagnostics_async(self, ls: LanguageServer, uri: str) -> None:
        """Async wrapper for debounced diagnostics.

        Args:
            ls: The language server instance
            uri: Document URI
        """
        try:
            doc = ls.workspace.get_text_document(uri)
            source = doc.source
            # Run the async diagnostics directly
            await self.run_diagnostics(ls, uri, source)
        except Exception as e:
            # Document might have been closed or other error
            logger.debug(f"Could not run diagnostics for {uri}: {e}")
