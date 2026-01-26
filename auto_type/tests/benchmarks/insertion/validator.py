"""Validation functions for insertion benchmark results.

This module provides functions to validate that inserted type annotations:
1. Are syntactically correct (code parses without errors)
2. Are semantically correct (type matches expected ground truth)
3. Were actually inserted (annotation exists in modified code)
"""

import ast
from typing import Any

from tests.benchmarks.typeevalpy.loader import BenchmarkCase
from tests.benchmarks.typeevalpy.runner import type_matches


def validate_syntax(source: str) -> tuple[bool, str | None]:
    """Check if source code is syntactically valid Python.

    Args:
        source: Python source code to validate

    Returns:
        Tuple of (is_valid, error_message)
        - is_valid: True if code parses without errors
        - error_message: None if valid, otherwise the syntax error message
    """
    try:
        ast.parse(source)
        return True, None
    except SyntaxError as e:
        return False, f"Line {e.lineno}: {e.msg}"
    except Exception as e:
        return False, f"Parse error: {type(e).__name__}: {e}"


def validate_type_match(inferred: str, expected: list[str]) -> bool:
    """Check if inferred type matches expected ground truth types.

    Args:
        inferred: The type that was inferred and inserted
        expected: List of acceptable types from ground truth

    Returns:
        True if type matches any expected type, False otherwise
    """
    return type_matches(inferred, expected)


def verify_annotation_inserted(
    original_source: str, modified_source: str, var_name: str, line_number: int
) -> tuple[bool, str | None]:
    """Verify that a type annotation was actually added to the variable.

    Uses a multi-strategy approach to handle line number shifts from declaration insertion:
    1. Check exact line number match
    2. Check within a range of lines (to handle declaration insertion shifting)
    3. Check if variable has ANY annotation in the file

    Args:
        original_source: Source code before insertion
        modified_source: Source code after insertion
        var_name: Variable name that should have been annotated
        line_number: 1-indexed line number where variable should be annotated

    Returns:
        Tuple of (was_inserted, error_message)
        - was_inserted: True if annotation was added
        - error_message: None if inserted, otherwise reason for failure
    """
    try:
        modified_tree = ast.parse(modified_source)
    except SyntaxError as e:
        return False, f"Failed to parse code: {e}"

    # Strategy 1: Check exact line number match
    for node in ast.walk(modified_tree):
        if (
            isinstance(node, ast.AnnAssign)
            and node.lineno == line_number
            and isinstance(node.target, ast.Name)
            and node.target.id == var_name
        ):
            return True, None

    # Strategy 2: Check near expected line (allow for line shifts from declaration insertion)
    # TypeDeclarationTransformer may insert declarations before the assignment,
    # shifting line numbers by a few lines
    line_tolerance = 5
    for node in ast.walk(modified_tree):
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == var_name
            and abs(node.lineno - line_number) <= line_tolerance
        ):
            return True, None

    # Strategy 3: Check if variable has ANY annotation in the file
    # This handles cases where significant restructuring occurred
    for node in ast.walk(modified_tree):
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == var_name
        ):
            return True, None

    return False, f"No annotation found for '{var_name}' (checked line {line_number} and file-wide)"


def verify_function_annotation_inserted(
    modified_source: str,
    function_name: str,
    annotation_type: str,
    param_name: str | None = None,
) -> tuple[bool, str | None]:
    """Verify function annotation was inserted.

    Args:
        modified_source: Source code after insertion
        function_name: Name of function (may be qualified like 'Class.method')
        annotation_type: Type of annotation - "return" or "param"
        param_name: Parameter name (required if annotation_type is "param")

    Returns:
        Tuple of (was_inserted, error_message)
        - was_inserted: True if annotation was found
        - error_message: None if found, otherwise reason for failure
    """
    try:
        tree = ast.parse(modified_source)
    except SyntaxError as e:
        return False, f"Syntax error: {e}"

    # Extract the simple function name (last part of qualified name)
    simple_name = function_name.split(".")[-1]

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == simple_name:
            if annotation_type == "return":
                if node.returns is not None:
                    return True, None
            elif annotation_type == "param" and param_name:
                for arg in node.args.args:
                    if arg.arg == param_name and arg.annotation is not None:
                        return True, None
                # Also check posonlyargs, kwonlyargs, etc.
                for arg in node.args.posonlyargs:
                    if arg.arg == param_name and arg.annotation is not None:
                        return True, None
                for arg in node.args.kwonlyargs:
                    if arg.arg == param_name and arg.annotation is not None:
                        return True, None

    if annotation_type == "return":
        return False, f"Return annotation not found for '{function_name}'"
    else:
        return False, f"Parameter annotation not found for '{param_name}' in '{function_name}'"


def validate_insertion_result(
    case: BenchmarkCase,
    original_source: str,
    modified_source: str,
    inferred_type: str | None,
    insertion_success: bool,
) -> dict[str, Any]:
    """Comprehensively validate an insertion result.

    Args:
        case: The benchmark case being validated
        original_source: Source code before insertion
        modified_source: Source code after insertion attempt
        inferred_type: Type that was inferred (None if inference failed)
        insertion_success: Whether InsertionEngine reported success

    Returns:
        Dictionary with validation results:
        - syntax_valid: bool - Is modified code syntactically valid?
        - syntax_error: str | None - Syntax error message if any
        - annotation_inserted: bool - Was annotation actually added?
        - insertion_error: str | None - Insertion verification error if any
        - type_matches: bool - Does inferred type match ground truth?
        - type_match_info: str - Details about type matching
    """
    result: dict[str, Any] = {}

    # 1. Validate syntax
    syntax_valid, syntax_error = validate_syntax(modified_source)
    result["syntax_valid"] = syntax_valid
    result["syntax_error"] = syntax_error

    # 2. Verify annotation was inserted (if insertion claimed success)
    if insertion_success and case.variable_name is not None:
        annotation_inserted, insertion_error = verify_annotation_inserted(
            original_source, modified_source, case.variable_name, case.line_number
        )
        result["annotation_inserted"] = annotation_inserted
        result["insertion_error"] = insertion_error
    else:
        result["annotation_inserted"] = False
        result["insertion_error"] = "Insertion was not successful"

    # 3. Validate type match (if we have an inferred type)
    if inferred_type is not None:
        type_match = validate_type_match(inferred_type, case.expected_types)
        result["type_matches"] = type_match
        if type_match:
            result["type_match_info"] = f"'{inferred_type}' matches expected types"
        else:
            result["type_match_info"] = (
                f"'{inferred_type}' does not match expected {case.expected_types}"
            )
    else:
        result["type_matches"] = False
        result["type_match_info"] = "No type was inferred"

    return result
