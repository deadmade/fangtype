"""Helper functions for type inference."""

import logging

logger = logging.getLogger(__name__)


def promote_numeric_types(left_type: str, right_type: str, operator: str) -> str:
    """Apply numeric type promotion rules.

    Args:
        left_type: Left operand type
        right_type: Right operand type
        operator: Operator string (for warning messages)

    Returns:
        Result type after promotion, or "Unknown" if incompatible
    """
    # Convert bool to int for arithmetic
    if left_type == "bool":
        left_type = "int"
    if right_type == "bool":
        right_type = "int"

    # Check if both are numeric
    if left_type in ("int", "float") and right_type in ("int", "float"):
        # If either is float, result is float
        if left_type == "float" or right_type == "float":
            return "float"
        # Both int
        return "int"

    # Incompatible types
    logger.warning(f"Incompatible types for {operator}: {left_type} and {right_type}")
    return "Unknown"


def infer_binop_result_type(left_type: str, op_name: str, right_type: str) -> str:
    """Infer result type of binary operation.

    Args:
        left_type: Type of left operand
        op_name: Operation name (e.g., "Add", "Mult", "BitOr")
        right_type: Type of right operand

    Returns:
        Inferred result type, or "Unknown" if cannot infer
    """
    # Handle Unknown operands
    if left_type == "Unknown" or right_type == "Unknown":
        return "Unknown"

    # Arithmetic operators
    if op_name == "Add":
        # String concatenation
        if left_type == "str" and right_type == "str":
            return "str"
        # List concatenation
        if left_type == "list" and right_type == "list":
            return "list"
        # Tuple concatenation
        if left_type == "tuple" and right_type == "tuple":
            return "tuple"
        # Numeric addition
        return promote_numeric_types(left_type, right_type, "+")

    elif op_name == "Sub":
        # Numeric subtraction
        return promote_numeric_types(left_type, right_type, "-")

    elif op_name == "Mult":
        # String repetition: str * int or int * str
        if (left_type == "str" and right_type == "int") or (
            left_type == "int" and right_type == "str"
        ):
            return "str"
        # List repetition: list * int or int * list
        if (left_type == "list" and right_type == "int") or (
            left_type == "int" and right_type == "list"
        ):
            return "list"
        # Tuple repetition: tuple * int or int * tuple
        if (left_type == "tuple" and right_type == "int") or (
            left_type == "int" and right_type == "tuple"
        ):
            return "tuple"
        # Numeric multiplication
        return promote_numeric_types(left_type, right_type, "*")

    elif op_name == "Div":
        # True division always returns float
        if left_type in ("int", "float", "bool") and right_type in (
            "int",
            "float",
            "bool",
        ):
            return "float"
        logger.warning(f"Incompatible types for /: {left_type} and {right_type}")
        return "Unknown"

    elif op_name == "FloorDiv":
        # Floor division
        result = promote_numeric_types(left_type, right_type, "//")
        # int // int → int, but int // float → float
        return result

    elif op_name == "Mod":
        # Modulo operator
        return promote_numeric_types(left_type, right_type, "%")

    elif op_name == "Pow":
        # Power operator
        result = promote_numeric_types(left_type, right_type, "**")
        return result

    # Bitwise operators
    elif op_name in ("BitAnd", "BitOr", "BitXor"):
        symbol = {"BitAnd": "&", "BitOr": "|", "BitXor": "^"}[op_name]

        # Set operations (union, intersection, symmetric difference)
        if op_name in ("BitAnd", "BitOr", "BitXor") and left_type == "set" and right_type == "set":
            return "set"

        # Integer bitwise operations
        # Convert bool to int for bitwise ops
        eff_left = "int" if left_type == "bool" else left_type
        eff_right = "int" if right_type == "bool" else right_type

        if eff_left == "int" and eff_right == "int":
            return "int"

        logger.warning(f"Incompatible types for {symbol}: {left_type} and {right_type}")
        return "Unknown"

    elif op_name in ("LShift", "RShift"):
        symbol = {"LShift": "<<", "RShift": ">>"}[op_name]

        # Shift operations require int operands
        eff_left = "int" if left_type == "bool" else left_type
        eff_right = "int" if right_type == "bool" else right_type

        if eff_left == "int" and eff_right == "int":
            return "int"

        logger.warning(f"Incompatible types for {symbol}: {left_type} and {right_type}")
        return "Unknown"

    # Unknown operator
    logger.debug(f"Unknown binary operator: {op_name}")
    return "Unknown"
