"""Protocol for diagnostic generation engines."""

from typing import Protocol, runtime_checkable

from lsprotocol import types  # noqa: TC002
from pygls.lsp.server import LanguageServer  # noqa: TC002


@runtime_checkable
class DiagnosticEngineProtocol(Protocol):
    """Protocol for diagnostic generation engines.

    Defines the interface for generating LSP diagnostics from mypy output.
    The primary implementation is DiagnosticEngine.

    All methods are async to support non-blocking diagnostic generation.
    """

    async def generate_diagnostics(self, source: str, uri: str) -> list[types.Diagnostic]:
        """Generate LSP diagnostics from mypy type checking.

        Args:
            source: The Python source code to analyze
            uri: The document URI

        Returns:
            List of LSP Diagnostic objects
        """
        ...

    async def run_diagnostics(self, ls: LanguageServer, uri: str, source: str) -> None:
        """Generate and publish diagnostics for a document.

        Args:
            ls: The language server instance
            uri: Document URI
            source: Document source code
        """
        ...

    def schedule_diagnostics(self, ls: LanguageServer, uri: str) -> None:
        """Schedule debounced diagnostics for a document.

        Args:
            ls: The language server instance
            uri: Document URI
        """
        ...
