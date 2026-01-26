"""Protocol for diagnostic generation engines."""

from typing import Protocol, runtime_checkable

from lsprotocol import types


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
