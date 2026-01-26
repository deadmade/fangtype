"""Mypy-based type validator for checking type annotation correctness."""

import asyncio
import keyword
import logging
import re
from dataclasses import dataclass
from typing import Any

from mypy import api

logger = logging.getLogger(__name__)


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


@dataclass
class MypyDiagnostic:
    """Structured mypy error for diagnostic reporting.

    Represents a single error, warning, or note from mypy analysis.
    """

    line: int  # 1-based (from mypy)
    column: int  # 0-based (from mypy, if available)
    end_column: int | None  # For ranges, if available
    message: str
    error_code: str | None  # e.g., "assignment", "arg-type", "return-value"
    severity: str  # "error", "warning", "note"


class MypyTypeValidator:
    """Type validator that uses mypy for semantic type checking.

    This validator performs full semantic validation using mypy:
    1. Validates type strings are syntactically correct
    2. Checks types are defined in scope (imports, classes, etc.)
    3. Verifies types are semantically valid according to mypy rules
    4. Ensures type annotations would actually work in the code

    Unlike the lightweight validator, this catches all issues that mypy
    would flag, ensuring we only suggest types that are truly valid.

    All public methods are async and use asyncio.to_thread() to run
    the blocking mypy subprocess calls without blocking the event loop.
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

    async def validate_file_full(self, source: str, timeout: float = 30.0) -> list[MypyDiagnostic]:
        """Run mypy on entire file and return ALL errors/warnings.

        Unlike validate_bulk which tests individual types, this validates
        the complete file and returns every issue mypy finds.

        This is used for comprehensive diagnostic reporting in the editor.

        Args:
            source: Complete Python source code
            timeout: Maximum time to wait for mypy (default 30s)

        Returns:
            List of structured mypy diagnostics (empty list if no errors or timeout)
        """
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._validate_file_full_sync, source),
                timeout=timeout,
            )
        except TimeoutError:
            logger.warning(f"Mypy file validation timed out after {timeout}s")
            return []

    def _validate_file_full_sync(self, source: str) -> list[MypyDiagnostic]:
        """Synchronous implementation of validate_file_full."""
        # Run mypy on the source code
        result = api.run([*self._mypy_flags, "-c", source])
        stdout, stderr, exit_code = result

        # Exit code 0 means no errors
        if exit_code == 0:
            return []

        # No output but non-zero exit - something went wrong
        if not stdout:
            logger.warning(f"Mypy validation failed with no output: {stderr}")
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

        # Regex pattern to match mypy error lines
        # Format: <string>:LINE:COL: SEVERITY: MESSAGE [CODE]
        # or:     <string>:LINE: SEVERITY: MESSAGE [CODE]
        pattern = re.compile(
            r"<string>:(\d+):(?:(\d+):)?\s*(error|warning|note):\s*(.+?)(?:\s+\[([^\]]+)\])?\s*$"
        )

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

    async def validate(self, type_str: str, source: str) -> bool:
        """Validate a single type string using mypy.

        Creates a test variable with the type annotation and validates it
        in the context of the provided source code (to respect imports,
        class definitions, etc.).

        Args:
            type_str: Type annotation to validate (e.g., "list[int]", "MyClass")
            source: Full source code for context (imports, classes, etc.)

        Returns:
            True if type is valid according to mypy, False otherwise
        """
        return await asyncio.to_thread(self._validate_sync, type_str, source)

    def _validate_sync(self, type_str: str, source: str) -> bool:
        """Synchronous implementation of validate."""
        # Special case: "Unknown" is not a valid type
        if type_str == "Unknown":
            return False

        # Create test code with the type annotation
        # Append a dummy variable assignment to the source
        test_code = f"{source}\n\n_auto_type_test: {type_str}\n"

        # Run mypy on the test code
        result = api.run([*self._mypy_flags, "-c", test_code])

        # result is a tuple: (stdout, stderr, exit_code)
        stdout, _stderr, exit_code = result

        # Exit code 0 means mypy found no errors
        if exit_code == 0:
            return True

        # If there were errors, check if they're related to our test variable
        # We only care about errors on the test variable line, not other errors in source
        if not stdout:
            return False

        # Parse errors - only reject if there's an error on our test annotation
        # Our test annotation is on the last line
        error_lines = stdout.strip().split("\n")

        for line in error_lines:
            # Check if error is about our test variable or undefined type in the test
            if "_auto_type_test" in line:
                # This error is about our test variable
                return False
            # Also check for "Name ... is not defined" which indicates undefined type
            if (
                ": error:" in line
                and "is not defined" in line
                and (f'Name "{type_str}"' in line or f"Name '{type_str}'" in line)
            ):
                return False

        # All errors are about other parts of the source, not our type annotation
        # This means the type itself is valid
        return True

    async def validate_insertion(
        self, source: str, variable_name: str, type_annotation: str
    ) -> tuple[bool, str]:
        """Validate a type annotation before insertion.

        Args:
            source: Source code where the type will be inserted
            variable_name: Name of the variable being annotated
            type_annotation: Type annotation to validate

        Returns:
            Tuple of (is_valid, error_message). error_message is empty if valid.
        """
        is_valid = await self.validate(type_annotation, source)
        if is_valid:
            return True, ""
        return False, f"Type '{type_annotation}' is not valid for variable '{variable_name}'"

    async def validate_bulk(
        self, types_map: dict[Any, str], source: str, timeout: float = 30.0
    ) -> dict[Any, str]:
        """Validate multiple types at once (more efficient than individual checks).

        Validates all types in a single mypy run. This is much more efficient
        than calling validate() for each type individually.

        Args:
            types_map: Dict of {key: type_str} to validate. Key can be str or tuple.
            source: Full source code for context
            timeout: Maximum time to wait for mypy (default 30s)

        Returns:
            Dict of {key: type_str} containing only valid types
        """
        if not types_map:
            return {}

        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._validate_bulk_sync, types_map, source),
                timeout=timeout,
            )
        except TimeoutError:
            logger.warning(f"Mypy bulk validation timed out after {timeout}s")
            return {}

    def _validate_bulk_sync(self, types_map: dict[Any, str], source: str) -> dict[Any, str]:
        """Synchronous implementation of validate_bulk."""
        # Create test code with all type annotations
        # Track which line corresponds to which variable
        # When mypy processes code with -c, line numbers start at 1

        test_lines = []
        if source:
            test_lines.append(source)
            if not source.endswith("\n"):
                test_lines.append("\n")

        # Calculate exactly how many lines the source (and potential newline) takes
        source_line_count = "".join(test_lines).count("\n")

        test_lines.append("# Auto-type test annotations\n")
        # Comment line is source_line_count + 1

        var_to_line: dict[Any, int] = {}
        # First variable will be on source_line_count + 2
        current_line = source_line_count + 2

        for key, type_str in types_map.items():
            if isinstance(key, tuple) and len(key) == 2 and isinstance(key[1], str):
                # Handle (line, name) keys
                var_name = key[1]
            else:
                var_name = str(key)

            sanitized_name = _sanitize_var_name(var_name)

            # Use unique suffix to allow same variable name multiple times
            unique_suffix = f"_{current_line}"
            test_lines.append(f"_auto_type_test_{sanitized_name}{unique_suffix}: {type_str}\n")

            var_to_line[key] = current_line
            current_line += 1

        test_code = "".join(test_lines)

        # Run mypy
        result = api.run([*self._mypy_flags, "-c", test_code])
        stdout, stderr, exit_code = result

        # If everything passed, return all types
        if exit_code == 0:
            return types_map.copy()

        # Parse errors to determine which types are invalid
        validated_types: dict[Any, str] = {}

        if not stdout:
            # No error output but non-zero exit - assume all invalid
            logger.warning(f"Mypy validation failed with no output: {stderr}")
            return {}

        # Parse error lines to find which test variables have errors
        # Format: <string>:LINE: error: MESSAGE
        error_lines = stdout.strip().split("\n")
        invalid_lines: set[int] = set()

        for line in error_lines:
            if ": error:" in line:
                # Extract line number
                try:
                    # Format: "<string>:LINE: error: ..."
                    line_str = line.split(":")[1]
                    line_num = int(line_str.strip())
                    invalid_lines.add(line_num)
                except (IndexError, ValueError):
                    # Couldn't parse line number, skip
                    continue

        # Return only types that didn't have errors on their lines
        for key, type_str in types_map.items():
            var_line = var_to_line[key]
            if var_line not in invalid_lines:
                validated_types[key] = type_str
            else:
                logger.debug(f"Filtered out invalid type: {key}: {type_str}")

        return validated_types
