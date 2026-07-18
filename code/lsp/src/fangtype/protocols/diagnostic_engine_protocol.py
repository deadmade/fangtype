"""Protocol for diagnostic generation engines."""

from typing import Protocol, runtime_checkable

from lsprotocol import types
from pygls.lsp.server import LanguageServer


@runtime_checkable
class DiagnosticEngineProtocol(Protocol):
    """Async interface for generating LSP diagnostics from mypy output (impl: DiagnosticEngine)."""

    async def generate_diagnostics(self, source: str, uri: str) -> list[types.Diagnostic]:
        """Generate LSP diagnostics from mypy type checking of source under uri."""
        ...

    async def run_diagnostics(self, ls: LanguageServer, uri: str, source: str) -> None:
        """Generate and publish diagnostics for a document."""
        ...

    def schedule_diagnostics(self, ls: LanguageServer, uri: str) -> None:
        """Schedule debounced diagnostics for a document."""
        ...

    def cancel_pending(self, uri: str) -> None:
        """Cancel and discard any pending debounced diagnostics timer for a URI."""
        ...
