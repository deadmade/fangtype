"""Mypy-based type validator for checking type annotation correctness."""

import logging
import re
from dataclasses import dataclass
from typing import Any

from mypy import api

logger = logging.getLogger(__name__)


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

    def validate_file_full(self, source: str) -> list[MypyDiagnostic]:
        """Run mypy on entire file and return ALL errors/warnings.

        Unlike validate_bulk which tests individual types, this validates
        the complete file and returns every issue mypy finds.

        This is used for comprehensive diagnostic reporting in the editor.

        Args:
            source: Complete Python source code

        Returns:
            List of structured mypy diagnostics (empty list if no errors)
        """
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

    def validate(self, type_str: str, source: str) -> bool:
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
        # Special case: "Unknown" is not a valid type
        if type_str == "Unknown":
            return False

        # Create test code with the type annotation
        # Append a dummy variable assignment to the source
        test_code = f"{source}\n\n_auto_type_test: {type_str}\n"

        # Run mypy on the test code
        result = api.run([*self._mypy_flags, "-c", test_code])

        # result is a tuple: (stdout, stderr, exit_code)
        stdout, stderr, exit_code = result

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

    def validate_bulk(self, types_map: dict[str, str], source: str) -> dict[str, str]:
        """Validate multiple types at once (more efficient than individual checks).

        Validates all types in a single mypy run. This is much more efficient
        than calling validate() for each type individually.

        Args:
            types_map: Dict of {var_name: type_str} to validate
            source: Full source code for context

        Returns:
            Dict of {var_name: type_str} containing only valid types
        """
        if not types_map:
            return {}

        # Create test code with all type annotations
        # Track which line corresponds to which variable
        # When mypy processes code with -c, line numbers start at 1
        test_lines = [source]
        if source and not source.endswith("\n"):
            test_lines.append("\n")
        test_lines.append("# Auto-type test annotations\n")

        # Calculate starting line number for test annotations
        # Count actual lines in source (split by newline)
        source_line_count = len(source.split("\n")) if source else 1
        # +1 for the comment line
        start_line = source_line_count + 1

        var_to_line: dict[str, int] = {}
        current_line = start_line

        for var_name, type_str in types_map.items():
            # Use unique names to avoid conflicts
            test_lines.append(f"_auto_type_test_{var_name}: {type_str}\n")
            var_to_line[var_name] = current_line
            current_line += 1

        test_code = "".join(test_lines)

        # Run mypy
        result = api.run([*self._mypy_flags, "-c", test_code])
        stdout, stderr, exit_code = result

        # If everything passed, return all types
        if exit_code == 0:
            return types_map.copy()

        # Parse errors to determine which types are invalid
        validated_types: dict[str, str] = {}

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
        for var_name, type_str in types_map.items():
            var_line = var_to_line[var_name]
            if var_line not in invalid_lines:
                validated_types[var_name] = type_str
            else:
                logger.debug(f"Filtered out invalid type: {var_name}: {type_str}")

        return validated_types

    def validate_insertion(self, source: str, var_name: str, type_str: str) -> tuple[bool, str]:
        """Validate that inserting a type annotation would be mypy-clean.

        Actually inserts the type annotation into the source and validates
        the complete file. This is the most thorough validation - it ensures
        the type annotation not only is valid, but also matches the actual value.

        Args:
            source: Original source code
            var_name: Variable name to annotate
            type_str: Type annotation to insert

        Returns:
            Tuple of (is_valid, error_message)
            - is_valid: True if insertion is valid
            - error_message: Empty string if valid, error details if invalid
        """
        # Use InsertionEngine to create the modified source
        # Import here to avoid circular dependency
        from auto_type.insertion import InsertionEngine

        insertion_engine = InsertionEngine()

        # Try to insert the type
        modified_source, success = insertion_engine.insert_type(source, var_name, type_str)

        if not success:
            return False, f"Could not insert type for variable '{var_name}'"

        # Validate the modified source with mypy
        result = api.run([*self._mypy_flags, "-c", modified_source])
        stdout, stderr, exit_code = result

        if exit_code == 0:
            return True, ""

        # Extract relevant error message
        error_msg = stdout.strip() if stdout else "Unknown mypy error"

        # Try to extract just the first error line for brevity
        if "\n" in error_msg:
            first_error = error_msg.split("\n")[0]
            # Remove file/line prefix from -c output
            if ": error:" in first_error:
                first_error = first_error.split(": error:", 1)[1].strip()
            error_msg = first_error

        logger.debug(f"Type insertion validation failed: {error_msg}")
        return False, error_msg

    def validate_function_signatures(
        self, functions: dict[str, dict[str, Any]], source: str
    ) -> dict[str, dict[str, Any]]:
        """Validate function signatures (parameters and return types).

        Args:
            functions: Dict of {func_name: {"params": {...}, "return": "..."}}
            source: Full source code for context

        Returns:
            Dict with same structure, containing only valid function signatures
        """
        if not functions:
            return {}

        validated_functions: dict[str, dict[str, Any]] = {}

        # Validate each function's signature
        for func_name, func_info in functions.items():
            validated_params: dict[str, str] = {}
            validated_return: str | None = None

            # Validate parameter types
            if func_info.get("params"):
                validated_params = self.validate_bulk(func_info["params"], source)

            # Validate return type
            if func_info.get("return"):
                return_type = func_info["return"]
                if self.validate(return_type, source):
                    validated_return = return_type

            # Include function if it has any validated types
            if validated_params or validated_return:
                validated_functions[func_name] = {
                    "params": validated_params,
                    "return": validated_return,
                }

        return validated_functions
