"""Mypy-based type validator for checking type annotation correctness."""

import asyncio
import keyword
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mypy import api

from auto_type.validation.mypy_diagnostic import MypyDiagnostic as MypyDiagnostic


@dataclass
class TypeValidationResult:
    """Result of validating a single type annotation.

    Contains the type string, validation status, and optional error message.

    Attributes:
        type_str: The type annotation string
        is_valid: True if mypy validated the type successfully
        error_message: Error message from mypy if validation failed, None otherwise
    """

    type_str: str
    is_valid: bool
    error_message: str | None = None


logger = logging.getLogger(__name__)

# Regex pattern to match mypy error lines
# Format: <string>:LINE:COL: SEVERITY: MESSAGE [CODE]
# or:     <string>:LINE: SEVERITY: MESSAGE [CODE]
pattern = re.compile(
    r"<string>:(\d+):(?:(\d+):)?\s*(error|warning|note):\s*(.+?)(?:\s+\[([^\]]+)\])?\s*$"
)


class MypyTypeValidator:
    """Type validator that uses mypy for semantic type checking.

    This validator performs full semantic validation using mypy:
    1. Validates type strings are syntactically correct
    2. Checks types are defined in scope (imports, classes, etc.)
    3. Verifies types are semantically valid according to mypy rules
    4. Ensures type annotations would actually work in the code

    Unlike the lightweight validator, this catches all issues that mypy
    would flag, ensuring we only suggest types that are truly valid.

    Public methods are async, and only the blocking mypy execution is
    offloaded with asyncio.to_thread() to avoid blocking the event loop.
    """

    def __init__(self) -> None:
        """Initialize the mypy validator."""
        # Mypy configuration flags
        self._mypy_flags = [
            "--no-error-summary",
            "--no-color-output",
            "--python-version",
            "3.12",
            "--disallow-untyped-defs",  # Report functions missing type annotations
            "--check-untyped-defs",  # Check bodies of untyped functions
            "--allow-untyped-calls",  # Allow calling untyped functions
            "--no-warn-return-any",  # Don't warn about Any returns
            "--allow-incomplete-defs",  # Allow partial annotations
        ]

        # When running inside a PyInstaller bundle, mypy cannot locate its
        # bundled typeshed via the normal __file__-relative path because the
        # compiled .so extension is extracted to a temp directory while data
        # files may remain in the embedded archive. Pass the explicit path
        # so mypy skips its own (broken) resolution logic.
        typeshed_dir = self._find_bundled_typeshed()
        if typeshed_dir:
            self._mypy_flags.extend(["--custom-typeshed-dir", typeshed_dir])
            logger.info("Using bundled typeshed: %s", typeshed_dir)

    @staticmethod
    def _find_bundled_typeshed() -> str | None:
        """Locate the typeshed directory when running inside a PyInstaller bundle.

        PyInstaller sets ``sys._MEIPASS`` to the temporary extraction directory.
        Mypy's typeshed is collected there under ``mypy/typeshed/``.

        Returns:
            Absolute path to the typeshed directory, or None if not running
            in a frozen environment or the directory is not found.
        """
        meipass: str | None = getattr(sys, "_MEIPASS", None)
        if meipass is None:
            return None
        typeshed_path = Path(meipass) / "mypy" / "typeshed"
        if typeshed_path.is_dir():
            return str(typeshed_path)
        logger.warning(
            "PyInstaller bundle detected but typeshed not found at %s",
            typeshed_path,
        )
        return None

    @staticmethod
    def _sanitize_var_name(name: str) -> str:
        """Sanitize a variable name for use in test code.

        Converts dotted paths, scope IDs, and other strings into valid
        Python identifiers by replacing non-alphanumeric characters with
        underscores and handling reserved keywords.

        Args:
            name: String to sanitize

        Returns:
            A valid Python identifier
        """
        # Replace non-alphanumeric characters with underscores
        sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", name)

        # Handle reserved keywords - check each part after splitting by underscore
        parts = sanitized.split("_")
        sanitized_parts = []
        for part in parts:
            if not part:
                continue
            if keyword.iskeyword(part) or keyword.issoftkeyword(part):
                sanitized_parts.append(f"{part}_")
            else:
                sanitized_parts.append(part)

        return "_".join(sanitized_parts)

    def _run_mypy_sync(self, code: str) -> tuple[str, str, int]:
        """Run mypy against in-memory code in the current thread."""
        args = [*self._mypy_flags, "-c", code]
        return api.run(args)

    async def validate_file_full(self, source: str) -> list[MypyDiagnostic]:
        """Run mypy on entire file and return ALL errors/warnings.

        Unlike validate_bulk which tests individual types, this validates
        the complete file and returns every issue mypy finds.

        This is used for comprehensive diagnostic reporting in the editor.

        Args:
            source: Complete Python source code

        Returns:
            List of structured mypy diagnostics (empty list if no errors or cancelled)
        """
        try:
            # Run in thread since mypy is blocking
            return await asyncio.to_thread(self._validate_file_full_sync, source)
        except asyncio.CancelledError:
            logger.info("Mypy file validation cancelled by client")
            return []

    def _validate_file_full_sync(self, source: str) -> list[MypyDiagnostic]:
        """Synchronous implementation of validate_file_full."""
        stdout, stderr, exit_code = self._run_mypy_sync(source)

        # Exit code 0 means no errors
        if exit_code == 0:
            return []

        # No output but non-zero exit - something went wrong
        if not stdout:
            self._log_empty_mypy_output(stderr, "file validation")
            return []

        # Parse mypy output
        return self._parse_mypy_output(stdout)

    def _parse_mypy_output(self, output: str) -> list[MypyDiagnostic]:
        """Parse mypy stdout into structured diagnostics.

        Mypy output format: <string>:LINE:COL: SEVERITY: MESSAGE [ERROR_CODE]
        Examples:
        - <string>:5:11: error: Incompatible types in assignment [assignment]
        - <string>:10: error: Missing return statement [return]
        - <string>:3:8: note: Revealed type is "builtins.int"

        Args:
            output: Mypy stdout string

        Returns:
            List of parsed diagnostics
        """
        diagnostics: list[MypyDiagnostic] = []

        for line in output.strip().split("\n"):
            match = pattern.match(line)
            if not match:
                # Skip lines that don't match (e.g., context lines)
                continue

            line_num_str, col_str, severity, message, error_code = match.groups()

            line_num = int(line_num_str)
            column = int(col_str) if col_str else 0
            # Mypy columns are 0-based already

            diagnostics.append(
                MypyDiagnostic(
                    line=line_num,
                    column=column,
                    end_column=None,  # Mypy doesn't provide end columns
                    message=message.strip(),
                    error_code=error_code,
                    severity=severity,
                )
            )

        return diagnostics

    def _log_empty_mypy_output(self, stderr: str, context: str) -> None:
        """Log warning when mypy returns non-zero exit but no stdout."""
        logger.warning(f"Mypy {context} failed with no output: {stderr}")

    async def validate_bulk(
        self, types_map: dict[Any, str], source: str
    ) -> dict[Any, TypeValidationResult]:
        """Validate multiple types at once (more efficient than individual checks).

        Validates all types in a single mypy run. This is much more efficient
        than validating each type in separate mypy runs.

        Args:
            types_map: Dict of {key: type_str} to validate. Key can be str or tuple.
            source: Full source code for context
        Returns:
            Dict of {key: TypeValidationResult} containing validation status.
        """
        if not types_map:
            return {}

        try:
            # Run in thread since mypy is blocking
            return await asyncio.to_thread(self._validate_bulk_sync, types_map, source)
        except asyncio.CancelledError:
            logger.info("Mypy bulk validation cancelled by client")
            return {}

    def _validate_bulk_sync(
        self, types_map: dict[Any, str], source: str
    ) -> dict[Any, TypeValidationResult]:
        """Synchronous implementation of validate_bulk."""
        if not types_map:
            return {}

        # Create test code with all type annotations.
        # Track which line corresponds to which variable.
        # When mypy processes code with -c, line numbers start at 1.
        test_lines = []
        if source:
            test_lines.append(source)
            if not source.endswith("\n"):
                test_lines.append("\n")

        # Calculate exactly how many lines the source (and potential newline) takes.
        source_line_count = "".join(test_lines).count("\n")

        test_lines.append("# Auto-type test annotations\n")
        # Comment line is source_line_count + 1.

        var_to_line: dict[Any, int] = {}
        line_to_key: dict[int, Any] = {}
        # First variable will be on source_line_count + 2.
        current_line = source_line_count + 2

        for key, type_str in types_map.items():
            if isinstance(key, tuple) and len(key) == 2 and isinstance(key[1], str):
                # Handle (line, name) keys.
                var_name = key[1]
            else:
                var_name = str(key)

            sanitized_name = self._sanitize_var_name(var_name)

            # Use unique suffix to allow same variable name multiple times.
            unique_suffix = f"_{current_line}"
            test_lines.append(f"_auto_type_test_{sanitized_name}{unique_suffix}: {type_str}\n")

            var_to_line[key] = current_line
            line_to_key[current_line] = key
            current_line += 1

        test_code = "".join(test_lines)

        stdout, stderr, exit_code = self._run_mypy_sync(test_code)

        # Initialize all results as valid.
        validation_results: dict[Any, TypeValidationResult] = {
            key: TypeValidationResult(type_str=type_str, is_valid=True)
            for key, type_str in types_map.items()
        }

        # If everything passed, return all types as valid.
        if exit_code == 0:
            return validation_results

        if not stdout:
            # No error output but non-zero exit - assume all invalid.
            self._log_empty_mypy_output(stderr, "bulk validation")
            return {
                key: TypeValidationResult(
                    type_str=type_str,
                    is_valid=False,
                    error_message="Validation failed",
                )
                for key, type_str in types_map.items()
            }

        # Parse mypy output and map errors back to input keys in a single pass.
        diagnostics = self._parse_mypy_output(stdout)
        for diagnostic in diagnostics:
            if diagnostic.severity != "error":
                continue

            key = line_to_key.get(diagnostic.line)
            if key is None:
                continue

            # Keep the first error reported for each input key.
            if validation_results[key].is_valid is False:
                continue

            type_str = types_map[key]
            validation_results[key] = TypeValidationResult(
                type_str=type_str,
                is_valid=False,
                error_message=diagnostic.message,
            )
            logger.debug(f"Invalid type: {key}: {type_str} - {diagnostic.message}")

        return validation_results
