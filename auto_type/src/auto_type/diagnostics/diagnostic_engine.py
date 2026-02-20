"""Engine for generating diagnostics from mypy type checking."""

import asyncio
import logging

from injector import inject
from lsprotocol import types
from pygls.lsp.server import LanguageServer  # noqa: TC002

from auto_type.utils.settings import Settings  # noqa: TC001
from auto_type.validation import MypyDiagnostic, MypyTypeValidator  # noqa: TC001

logger = logging.getLogger(__name__)


class DiagnosticEngine:
    """Generates LSP diagnostics from mypy type checking.

    This engine runs mypy on the entire file and converts all mypy errors,
    warnings, and notes into LSP diagnostics that can be displayed in the editor.

    All methods are async to work with async validators.
    """

    @inject
    def __init__(self, mypy_validator: MypyTypeValidator, settings: Settings) -> None:
        """Initialize the diagnostic engine.

        Args:
            mypy_validator: The mypy validator to use for type checking
            settings: Server settings
        """
        self._timers: dict[str, asyncio.TimerHandle] = {}
        self.mypy_validator = mypy_validator
        self.settings = settings

    async def generate_diagnostics(self, source: str, uri: str) -> list[types.Diagnostic]:
        """Run mypy and convert all errors to LSP diagnostics.

        Args:
            source: The Python source code to analyze
            uri: The document URI (for logging/debugging)

        Returns:
            List of LSP Diagnostic objects for each mypy issue
        """
        if not self.settings.mypy_enabled:
            logger.debug(f"Diagnostics disabled in settings for {uri}")
            return []

        try:
            # Run mypy validation on the entire file (async)
            mypy_diagnostics = await self.mypy_validator.validate_file_full(source)

            # Convert to LSP diagnostics
            lsp_diagnostics = []
            for mypy_diag in mypy_diagnostics:
                lsp_diag = self._convert_to_lsp_diagnostic(mypy_diag, source)
                if lsp_diag:
                    lsp_diagnostics.append(lsp_diag)

            logger.debug(f"Generated {len(lsp_diagnostics)} diagnostics from mypy for {uri}")
            return lsp_diagnostics

        except Exception as e:
            logger.error(f"Error generating diagnostics: {e}", exc_info=True)
            return []

    async def run_diagnostics(self, ls: LanguageServer, uri: str, source: str) -> None:
        """Generate and publish diagnostics for a document.

        Args:
            ls: The language server instance
            uri: Document URI
            source: Document source code
        """
        try:
            diagnostics = await self.generate_diagnostics(source, uri)
            logger.info(f"Publishing {len(diagnostics)} diagnostics for {uri}")
            ls.text_document_publish_diagnostics(
                types.PublishDiagnosticsParams(uri=uri, diagnostics=diagnostics)
            )
        except Exception as e:
            logger.error(f"Error running diagnostics: {e}", exc_info=True)
            ls.text_document_publish_diagnostics(
                types.PublishDiagnosticsParams(uri=uri, diagnostics=[])
            )

    def schedule_diagnostics(self, ls: LanguageServer, uri: str) -> None:
        """Schedule debounced diagnostics for a document.

        Args:
            ls: The language server instance
            uri: Document URI
        """
        if uri in self._timers:
            self._timers[uri].cancel()

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.get_event_loop()

        timer = loop.call_later(
            0.5,
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
            await self.run_diagnostics(ls, uri, source)
        except Exception as e:
            logger.debug(f"Could not run diagnostics for {uri}: {e}")

    def _convert_to_lsp_diagnostic(
        self, mypy_diag: MypyDiagnostic, source: str
    ) -> types.Diagnostic | None:
        """Convert mypy diagnostic to LSP Diagnostic with filtering.

        Args:
            mypy_diag: Structured mypy diagnostic
            source: Source code (used to calculate proper ranges)

        Returns:
            LSP Diagnostic object or None if filtered out
        """
        # Downgrade annotation-related errors to warnings for better UX
        # These are style/completeness issues, not critical errors
        ANNOTATION_ERROR_CODES = {
            "no-untyped-def",  # Function without type annotations
            "no-untyped-call",  # Calling untyped function (if we ever enable it)
        }

        # Determine actual severity
        severity = mypy_diag.severity
        if mypy_diag.severity == "error" and mypy_diag.error_code in ANNOTATION_ERROR_CODES:
            # Downgrade annotation-related errors to warnings
            severity = "warning"

        # Map mypy severity to LSP severity
        severity_map = {
            "error": types.DiagnosticSeverity.Error,
            "warning": types.DiagnosticSeverity.Warning,
            "note": types.DiagnosticSeverity.Information,
        }

        lsp_severity = severity_map.get(severity, types.DiagnosticSeverity.Error)

        # Apply severity filter
        threshold_map = {
            "error": types.DiagnosticSeverity.Error,
            "warning": types.DiagnosticSeverity.Warning,
            "information": types.DiagnosticSeverity.Information,
            "hint": types.DiagnosticSeverity.Hint,
        }
        threshold = threshold_map.get(
            self.settings.diagnostic_severity.lower(), types.DiagnosticSeverity.Information
        )

        # Note: LSP severity values are 1 (Error) to 4 (Hint).
        # We want lsp_severity <= threshold to show it.
        if lsp_severity.value > threshold.value:
            return None

        # Convert line number (mypy uses 1-based, LSP uses 0-based)
        line = mypy_diag.line - 1

        # Column is already 0-based from mypy
        start_col = mypy_diag.column

        # Calculate end column
        # If mypy provided an end column, use it; otherwise estimate
        if mypy_diag.end_column is not None:
            end_col = mypy_diag.end_column
        else:
            # Try to find a reasonable end position
            # Default to highlighting a few characters
            end_col = start_col + 1
            try:
                lines = source.splitlines()
                if 0 <= line < len(lines):
                    line_text = lines[line]
                    # Extend to end of word/identifier if possible
                    if start_col < len(line_text):
                        pos = start_col
                        while pos < len(line_text) and (
                            line_text[pos].isalnum() or line_text[pos] == "_"
                        ):
                            pos += 1
                        if pos > start_col:
                            end_col = pos
            except Exception:
                # Fall back to single character if anything goes wrong
                pass

        return types.Diagnostic(
            range=types.Range(
                start=types.Position(line=line, character=start_col),
                end=types.Position(line=line, character=end_col),
            ),
            severity=severity_map.get(severity, types.DiagnosticSeverity.Error),
            source="mypy",
            message=mypy_diag.message,
            code=mypy_diag.error_code,
        )
