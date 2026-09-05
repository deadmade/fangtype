"""Engine for generating diagnostics from mypy type checking."""

import asyncio
import logging

from injector import inject
from lsprotocol import types
from pygls.lsp.server import LanguageServer

from fangtype.utils.position_encoding import codepoint_to_utf16
from fangtype.utils.settings import Settings
from fangtype.validation import MypyDiagnostic, MypyTypeValidator

logger = logging.getLogger(__name__)

# Annotation-related errors are style/completeness issues, not critical — downgrade to warnings.
_ANNOTATION_ERROR_CODES = {
    "no-untyped-def",  # Function without type annotations
    "no-untyped-call",  # Calling untyped function (if we ever enable it)
}

# Map mypy severity strings to LSP severities.
_SEVERITY_MAP = {
    "error": types.DiagnosticSeverity.Error,
    "warning": types.DiagnosticSeverity.Warning,
    "note": types.DiagnosticSeverity.Information,
}

# Map the configured diagnostic-severity threshold string to an LSP severity.
_THRESHOLD_MAP = {
    "error": types.DiagnosticSeverity.Error,
    "warning": types.DiagnosticSeverity.Warning,
    "information": types.DiagnosticSeverity.Information,
    "hint": types.DiagnosticSeverity.Hint,
}


class DiagnosticEngine:
    """Runs mypy on the whole file and converts its errors/warnings/notes into LSP diagnostics."""

    # @inject's Any-leaking overloads can't satisfy disallow_any_expr; hence the ignore below.
    @inject  # type: ignore[misc]
    def __init__(self, mypy_validator: MypyTypeValidator, settings: Settings) -> None:
        """Initialize the diagnostic engine with a mypy validator and server settings."""
        self._timers: dict[str, asyncio.TimerHandle] = {}
        self.mypy_validator = mypy_validator
        self.settings = settings

    async def generate_diagnostics(self, source: str, uri: str) -> list[types.Diagnostic]:
        """Run mypy on source and return an LSP Diagnostic per issue (empty if disabled)."""
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
        """Generate diagnostics for a document and publish them to the client."""
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
        """Schedule debounced (0.5s) diagnostics for a document, cancelling any prior timer."""
        if uri in self._timers:
            self._timers[uri].cancel()

        loop = asyncio.get_running_loop()

        def _fire() -> None:
            # The firing timer is always this uri's current entry, so dropping it is safe.
            self._timers.pop(uri, None)
            asyncio.run_coroutine_threadsafe(self._run_diagnostics_async(ls, uri), loop)

        timer = loop.call_later(0.5, _fire)
        self._timers[uri] = timer

    def cancel_pending(self, uri: str) -> None:
        """Cancel any pending debounced timer for a URI (on close, so _timers can't leak)."""
        timer = self._timers.pop(uri, None)
        if timer is not None:
            timer.cancel()

    async def _run_diagnostics_async(self, ls: LanguageServer, uri: str) -> None:
        """Async wrapper that fetches the document source and runs debounced diagnostics."""
        try:
            doc = ls.workspace.get_text_document(uri)
            source = doc.source
            await self.run_diagnostics(ls, uri, source)
            # Force a clean inlay re-pull so hints settle after a change (e.g. an applied insert);
            # VSCode's own re-pull can stick if it gets cancelled, leaving stale hints.
            await ls.workspace_inlay_hint_refresh_async(None)
        except Exception as e:
            logger.debug(f"Could not run diagnostics for {uri}: {e}")

    def _convert_to_lsp_diagnostic(
        self, mypy_diag: MypyDiagnostic, source: str
    ) -> types.Diagnostic | None:
        """Convert a mypy diagnostic to an LSP Diagnostic, or None if filtered by severity."""
        # Determine actual severity, downgrading annotation-related errors to warnings for UX.
        severity = mypy_diag.severity
        if mypy_diag.severity == "error" and mypy_diag.error_code in _ANNOTATION_ERROR_CODES:
            severity = "warning"

        lsp_severity = _SEVERITY_MAP.get(severity, types.DiagnosticSeverity.Error)

        # Apply severity filter
        threshold = _THRESHOLD_MAP.get(
            self.settings.diagnostic_severity.lower(), types.DiagnosticSeverity.Information
        )

        # LSP severities are 1 (Error) to 4 (Hint); show only when lsp_severity <= threshold.
        if lsp_severity.value > threshold.value:
            return None

        # Convert line number (mypy uses 1-based, LSP uses 0-based)
        line = mypy_diag.line - 1

        # Column is already 0-based from mypy
        start_col = mypy_diag.column

        # Mypy gives no end column: extend to end of word, defaulting to a single character.
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

        # Convert code-point columns to UTF-16 units so LSP ranges land right on non-ASCII lines.
        diag_lines = source.splitlines()
        if 0 <= line < len(diag_lines):
            diag_line_text = diag_lines[line]
            start_col = codepoint_to_utf16(diag_line_text, start_col)
            end_col = codepoint_to_utf16(diag_line_text, end_col)

        return types.Diagnostic(
            range=types.Range(
                start=types.Position(line=line, character=start_col),
                end=types.Position(line=line, character=end_col),
            ),
            severity=lsp_severity,
            source="mypy",
            message=mypy_diag.message,
            code=mypy_diag.error_code,
        )
