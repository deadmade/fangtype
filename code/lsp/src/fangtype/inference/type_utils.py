"""Type utility functions for type name normalization and manipulation."""

from __future__ import annotations

import ast
import re

_CALLABLE_SIGNATURE_PATTERN = re.compile(
    r"^(<lambda>|[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*\([^)]*\)\s*->\s*.+$"
)
_CALLABLE_CALL_PATTERN = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*\([^)]*\)$")


# Type names this module writes itself rather than reading off an inferred object. Nothing in
# the inference can resolve their import, because they name no symbol the analysed file refers
# to, so the import they need is stated here. Both are spelled from collections.abc rather than
# typing, which is deprecated for them since 3.9.
_SYNTHESISED_TYPE_IMPORTS: dict[str, tuple[str, str]] = {
    "Callable": ("collections.abc", "Callable"),
    "Generator": ("collections.abc", "Generator"),
}

# Jedi reports a function-valued or generator-valued binding by its runtime class, so a dict of
# functions comes back as `dict[str, FunctionType]`. That spelling names `types.FunctionType`,
# which the analysed file does not import, and it is a valid expression so the validity gate
# passes it straight through to mypy as an undefined name. Rewriting to the collections.abc
# spelling gives it an importable name, and it is also the assignable one: `types.FunctionType`
# is a nominal class that typeshed does not make a supertype of every `Callable`, so annotating
# with it would reject values the binding really holds.
_RUNTIME_CLASS_SPELLINGS = {
    "FunctionType": "Callable",
    "GeneratorType": "Generator",
}


def annotation_mentions_name(annotation: str, name: str) -> bool:
    """Whether an annotation refers to a bare name, as a whole identifier rather than a substring.

    ``Decimal`` is mentioned by ``Decimal``, by ``Decimal | None`` and by ``list[Decimal]``, and
    is not mentioned by ``DecimalLike``.
    """
    return re.search(rf"\b{re.escape(name)}\b", annotation) is not None


def import_for_annotation(annotation: str) -> tuple[str, str] | None:
    """The import a synthesised type name in this annotation needs, or None when it needs none."""
    for name, hint in _SYNTHESISED_TYPE_IMPORTS.items():
        if annotation_mentions_name(annotation, name):
            return hint
    return None


def _is_valid_type_expression(type_str: str) -> bool:
    """Check if a type string can be parsed as a Python expression."""
    try:
        ast.parse(type_str, mode="eval")
        return True
    except SyntaxError:
        return False


def sanitize_inferred_type(type_str: str) -> str:
    """Sanitize malformed inferred type strings into insertable annotation syntax."""
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
    """Split a comma-separated type argument string, respecting bracket-depth nesting."""
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


def _split_union(type_str: str) -> list[str]:
    """Split on top-level ``|`` only, respecting ``[]`` and ``()`` nesting."""
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    i = 0
    while i < len(type_str):
        ch = type_str[i]
        if ch in "[(":
            depth += 1
            current.append(ch)
        elif ch in "])":
            depth -= 1
            current.append(ch)
        elif ch == "|" and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
        i += 1
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return [p for p in parts if p]


def simplify_union_type(type_str: str) -> str:
    """Simplify a union type by removing duplicate members."""
    parts = _split_union(type_str)
    if len(parts) <= 1:
        return type_str

    seen: set[str] = set()
    unique_parts: list[str] = []
    for part in parts:
        part = part.strip()
        if part and part not in seen:
            seen.add(part)
            unique_parts.append(part)

    # Any absorbs every other member (Any | T == Any, including Any | None).
    if "Any" in seen:
        return "Any"

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
    """Normalize a type name to 3.12+ syntax; return "Unknown" if the result is not valid."""
    if not type_str or not type_str.strip():
        return type_str

    result = _normalize_type_name_core(type_str)
    return result if _is_valid_type_expression(result) else "Unknown"


def _normalize_type_name_core(type_str: str) -> str:
    """Normalize a type name to 3.12+ syntax (Optional/Union -> ``|``, List/Dict -> builtins)."""
    if not type_str:
        return type_str

    type_str = sanitize_inferred_type(type_str)
    if not type_str or type_str == "Unknown":
        return type_str

    # Handle Type[X] -> X (Jedi sometimes returns type class instead of instance)
    if type_str.startswith("Type[") and type_str.endswith("]"):
        inner = type_str[5:-1]  # Extract X from Type[X]
        return _normalize_type_name_core(inner)

    # Handle Optional[T] -> T | None
    if type_str.startswith("Optional[") and type_str.endswith("]"):
        inner = type_str[9:-1]  # Extract T from Optional[T]
        normalized_inner = _normalize_type_name_core(inner)
        return simplify_union_type(f"{normalized_inner} | None")

    # Handle Union[A, B] -> A | B
    if type_str.startswith("Union[") and type_str.endswith("]"):
        inner = type_str[6:-1]  # Extract A, B from Union[A, B]
        args = split_type_args(inner)
        normalized_args = [_normalize_type_name_core(arg) for arg in args]
        # Remove None from parts and handle it at the end if present
        has_none = "None" in normalized_args
        if has_none:
            normalized_args = [p for p in normalized_args if p != "None"]

        result = " | ".join(sorted(normalized_args))
        if has_none:
            result = f"{result} | None"
        return simplify_union_type(result)

    # Handle bare PEP 604 unions (A | B) before the generic branch so subscripts and Any collapse.
    union_parts = _split_union(type_str)
    if len(union_parts) > 1:
        normalized = [_normalize_type_name_core(part) for part in union_parts]
        return simplify_union_type(" | ".join(normalized))

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
            **_RUNTIME_CLASS_SPELLINGS,
        }
        new_base = base_mapping.get(base_type, base_type)

        # 2a: repair an empty subscript (e.g. "tuple[]") to the bare base, a valid expression.
        if not args:
            return new_base

        # Normalize each argument and deduplicate unions within args
        normalized_args = [simplify_union_type(_normalize_type_name_core(arg)) for arg in args]

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
        **_RUNTIME_CLASS_SPELLINGS,
    }

    return simple_mapping.get(type_str, type_str)
