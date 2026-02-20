"""Type utility functions for type name normalization and manipulation."""

from __future__ import annotations

import ast
import re

_CALLABLE_SIGNATURE_PATTERN = re.compile(
    r"^(<lambda>|[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*\([^)]*\)\s*->\s*.+$"
)
_CALLABLE_CALL_PATTERN = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*\([^)]*\)$")


def _is_valid_type_expression(type_str: str) -> bool:
    """Check if a type string can be parsed as a Python expression."""
    try:
        ast.parse(type_str, mode="eval")
        return True
    except SyntaxError:
        return False


def sanitize_inferred_type(type_str: str) -> str:
    """Sanitize malformed inferred type strings into insertable annotation syntax.

    Args:
        type_str: Raw inferred type string

    Returns:
        Sanitized type string suitable for annotation insertion
    """
    cleaned = type_str.strip()
    if not cleaned or cleaned == "Unknown":
        return cleaned

    if _CALLABLE_SIGNATURE_PATTERN.match(cleaned):
        return "Callable"

    if cleaned.startswith("<lambda>"):
        return "Callable"

    if _CALLABLE_CALL_PATTERN.match(cleaned):
        return "Callable"

    repaired = cleaned
    while repaired.endswith(")") and not _is_valid_type_expression(repaired):
        repaired = repaired[:-1].strip()
        if repaired and _is_valid_type_expression(repaired):
            return repaired

    return cleaned


def split_type_args(args_str: str) -> list[str]:
    """Split a comma-separated type argument string, respecting brackets.

    Handles nested generics correctly by tracking bracket depth.

    Args:
        args_str: String containing type arguments like "int, List[str]"

    Returns:
        List of individual type argument strings
    """
    args = []
    current = []
    depth = 0

    for char in args_str:
        if char == "[":
            depth += 1
            current.append(char)
        elif char == "]":
            depth -= 1
            current.append(char)
        elif char == "," and depth == 0:
            # Only split at top level
            arg = "".join(current).strip()
            if arg:
                args.append(arg)
            current = []
        else:
            current.append(char)

    # Add the last argument
    if current:
        arg = "".join(current).strip()
        if arg:
            args.append(arg)

    return args


def simplify_union_type(type_str: str) -> str:
    """Simplify union types by removing duplicates.

    Handles cases like:
    - list[int] | list[int] -> list[int]
    - str | str | int -> int | str

    Args:
        type_str: Type string that may contain union with duplicates

    Returns:
        Simplified type string with duplicate union members removed
    """
    if " | " not in type_str:
        return type_str

    # Split by union separator
    parts = type_str.split(" | ")

    # Deduplicate while preserving order of first occurrence
    seen: set[str] = set()
    unique_parts: list[str] = []
    for part in parts:
        part = part.strip()
        if part not in seen:
            seen.add(part)
            unique_parts.append(part)

    # Handle None at end
    has_none = "None" in unique_parts
    if has_none:
        unique_parts = [p for p in unique_parts if p != "None"]

    if not unique_parts:
        return "None" if has_none else type_str

    result = " | ".join(unique_parts)
    if has_none:
        result = f"{result} | None"

    return result


def normalize_type_name(type_str: str) -> str:
    """Normalize a type name to Python 3.12+ syntax.

    Converts old-style typing module imports to modern syntax:
    - Optional[T] -> T | None
    - Union[A, B] -> A | B
    - List[int] -> list[int]
    - Dict[str, int] -> dict[str, int]
    - Set[T] -> set[T]
    - Tuple[A, B] -> tuple[A, B]
    - FrozenSet[T] -> frozenset[T]

    Args:
        type_str: The type string to normalize

    Returns:
        Normalized type string
    """
    if not type_str:
        return type_str

    type_str = sanitize_inferred_type(type_str)
    if not type_str or type_str == "Unknown":
        return type_str

    # Handle Type[X] -> X (Jedi sometimes returns type class instead of instance)
    if type_str.startswith("Type[") and type_str.endswith("]"):
        inner = type_str[5:-1]  # Extract X from Type[X]
        return normalize_type_name(inner)

    # Handle Optional[T] -> T | None
    if type_str.startswith("Optional[") and type_str.endswith("]"):
        inner = type_str[9:-1]  # Extract T from Optional[T]
        normalized_inner = normalize_type_name(inner)
        return f"{normalized_inner} | None"

    # Handle Union[A, B] -> A | B
    if type_str.startswith("Union[") and type_str.endswith("]"):
        inner = type_str[6:-1]  # Extract A, B from Union[A, B]
        args = split_type_args(inner)
        normalized_args = [normalize_type_name(arg) for arg in args]
        # Remove None from parts and handle it at the end if present
        has_none = "None" in normalized_args
        if has_none:
            normalized_args = [p for p in normalized_args if p != "None"]

        result = " | ".join(sorted(normalized_args))
        if has_none:
            result = f"{result} | None"
        return simplify_union_type(result)

    # Handle generics with parameters: Generic[arg1, arg2, ...]
    if "[" in type_str and type_str.endswith("]"):
        bracket_idx = type_str.index("[")
        base_type = type_str[:bracket_idx]
        args_str = type_str[bracket_idx + 1 : -1]
        args = split_type_args(args_str)

        # Convert old-style typing names to builtins
        base_mapping = {
            "List": "list",
            "Dict": "dict",
            "Set": "set",
            "Tuple": "tuple",
            "FrozenSet": "frozenset",
            "Generator": "generator",
        }
        new_base = base_mapping.get(base_type, base_type)

        # Normalize each argument and deduplicate unions within args
        normalized_args = [simplify_union_type(normalize_type_name(arg)) for arg in args]

        # Ensure dict/defaultdict have 2 arguments
        if new_base in ("dict", "defaultdict") and len(normalized_args) == 1:
            normalized_args.append("Any")

        return f"{new_base}[{', '.join(normalized_args)}]"

    # Handle simple old-style names without parameters
    simple_mapping = {
        "List": "list",
        "Dict": "dict",
        "Set": "set",
        "Tuple": "tuple",
        "FrozenSet": "frozenset",
        "callable": "Callable",
    }

    return simple_mapping.get(type_str, type_str)
