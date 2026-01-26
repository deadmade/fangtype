"""Engine for generating diagnostics from mypy type checking."""

import logging

from injector import inject
from lsprotocol import types

from auto_type.validation import MypyDiagnostic, MypyTypeValidator

logger = logging.getLogger(__name__)


class DiagnosticEngine:
    """Generates LSP diagnostics from mypy type checking.

    This engine runs mypy on the entire file and converts all mypy errors,
    warnings, and notes into LSP diagnostics that can be displayed in the editor.

    All methods are async to work with async validators.
    """

    @inject
    def __init__(self, mypy_validator: MypyTypeValidator) -> None:
        """Initialize the diagnostic engine.

        Args:
            mypy_validator: The mypy validator to use for type checking
        """
        self.mypy_validator = mypy_validator

    async def generate_diagnostics(self, source: str, uri: str) -> list[types.Diagnostic]:
        """Run mypy and convert all errors to LSP diagnostics.

        Args:
            source: The Python source code to analyze
            uri: The document URI (for logging/debugging)

        Returns:
            List of LSP Diagnostic objects for each mypy issue
        """
        try:
            # Run mypy validation on the entire file (async)
            mypy_diagnostics = await self.mypy_validator.validate_file_full(source)

            # Convert to LSP diagnostics
            lsp_diagnostics = []
            for mypy_diag in mypy_diagnostics:
                lsp_diag = self._convert_to_lsp_diagnostic(mypy_diag, source)
                lsp_diagnostics.append(lsp_diag)

            logger.debug(f"Generated {len(lsp_diagnostics)} diagnostics from mypy for {uri}")
            return lsp_diagnostics

        except Exception as e:
            logger.error(f"Error generating diagnostics: {e}", exc_info=True)
            return []

    def _convert_to_lsp_diagnostic(
        self, mypy_diag: MypyDiagnostic, source: str
    ) -> types.Diagnostic:
        """Convert mypy diagnostic to LSP Diagnostic.

        Args:
            mypy_diag: Structured mypy diagnostic
            source: Source code (used to calculate proper ranges)

        Returns:
            LSP Diagnostic object
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
