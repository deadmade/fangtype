"""Jedi type formatting utilities: format Jedi type objects into readable type hints."""

import logging
from typing import Any

from fangtype.inference.type_utils import normalize_type_name

logger = logging.getLogger(__name__)

# Container builtins carry element params (``list[int]``), so consult get_type_hint() not bare name.
_CONTAINER_BUILTINS = frozenset({"list", "dict", "set", "tuple", "frozenset"})


def format_jedi_type(jedi_type: Any) -> str:
    """Format a Jedi type object (Name, Instance, etc.) into a readable type-hint string."""
    if jedi_type is None:
        return "Unknown"

    try:
        # Try to get the type name directly
        type_name = str(jedi_type.name)

        # A plain function object isn't a type; only a Callable[...] hint counts, not its bare name.
        is_plain_function: bool = str(getattr(jedi_type, "type", None)) == "function"

        # Handle non-container builtins directly; containers fall through to keep element params.
        if (
            jedi_type.module_name == "builtins"
            and type_name
            and type_name not in _CONTAINER_BUILTINS
            and not is_plain_function
        ):
            return normalize_type_name(type_name)

        # Try to get type hint if available
        if hasattr(jedi_type, "get_type_hint"):
            try:
                hint = jedi_type.get_type_hint()
                if hint and (not is_plain_function or hint.startswith("Callable")):
                    return normalize_type_name(hint)
            except Exception:
                # get_type_hint() may raise from Jedi generics; fall through to bare-name.
                pass

        # Try to infer the type
        inferences = jedi_type.infer()
        if inferences:
            for inference in inferences:
                if inference.type == "instance":
                    try:
                        instance_name = inference.name
                        if instance_name:
                            return normalize_type_name(str(instance_name))
                    except AttributeError:
                        pass
                    except TypeError:
                        pass

        # Fallback to the original type name -- but not for plain functions (bare name not a type).
        if type_name and not is_plain_function:
            return normalize_type_name(type_name)

    except Exception as e:
        logger.debug(f"Error formatting Jedi type: {e}")

    return "Unknown"


def extract_type_hint(name: Any, inferences: list[Any]) -> str | None:
    """Extract a type-hint string from a Jedi Name and its inferences, or None if unavailable."""
    # Try to get type hint from name
    if hasattr(name, "get_type_hint"):
        try:
            hint = name.get_type_hint()
            if hint:
                return normalize_type_name(hint)
        except Exception:
            pass

    # Fall back to formatting first inference
    if inferences:
        result = format_jedi_type(inferences[0])
        # "Unknown" is truthy but not a real hint -- return None so the caller's
        # `... or format_types(inferences)` fallback (which unions ALL inferences) still runs.
        return result if result != "Unknown" else None

    return None


def format_types(inferences: list[Any]) -> str:
    """Format a list of Jedi type inferences into a type string (union-joined when multiple)."""
    if not inferences:
        return "Unknown"

    if len(inferences) == 1:
        return format_jedi_type(inferences[0])

    # Handle multiple inferences (union type)
    type_names = []
    for inf in inferences:
        type_name = format_jedi_type(inf)
        if type_name and type_name != "Unknown":
            type_names.append(type_name)

    if not type_names:
        return "Unknown"

    if len(type_names) == 1:
        return type_names[0]

    # Remove duplicates while preserving order
    seen = set()
    unique_types = []
    for t in type_names:
        if t not in seen:
            seen.add(t)
            unique_types.append(t)

    return " | ".join(unique_types)


def infer_return_type(func_name: Any) -> str:
    """Infer the return type of a function (Jedi Name) using Jedi, as a string."""
    if func_name is None:
        return "Unknown"

    try:
        # Try to infer from return statements using execute()
        return_values = func_name.execute()
        if return_values:
            return_types = set()
            for rv in return_values:
                try:
                    type_name = str(rv.name)
                    is_container = rv.module_name == "builtins" and type_name in _CONTAINER_BUILTINS
                    # Prefer the parameterized hint so container returns keep element types.
                    rv_hint = None
                    if (is_container or rv.module_name != "builtins") and hasattr(
                        rv, "get_type_hint"
                    ):
                        try:
                            rv_hint = rv.get_type_hint()
                        except Exception:
                            rv_hint = None
                    if rv_hint:
                        return_types.add(rv_hint)
                    elif rv.module_name == "builtins" and type_name:
                        return_types.add(type_name)
                except AttributeError:
                    pass
                except TypeError:
                    pass

            if return_types:
                # Keep None members: returning `X` on one path and `None` on another is `X | None`.
                if "NoneType" in return_types:
                    return_types.discard("NoneType")
                    return_types.add("None")

                if len(return_types) == 1:
                    type_str = return_types.pop()
                else:
                    type_str = " | ".join(sorted(return_types))

                normalized = normalize_type_name(type_str)
                if normalized and normalized != "Unknown":
                    return normalized

    except Exception:
        pass

    try:
        # Fallback to general inference
        inferences = func_name.infer()
        if inferences:
            for inference in inferences:
                if inference.type == "function":
                    try:
                        hint = inference.get_type_hint()
                        if hint and " -> " in hint:
                            return_type = hint.split(" -> ")[-1].strip()
                            if return_type and return_type not in ("None", "NoneType"):
                                normalized = normalize_type_name(return_type)
                                if normalized and normalized != "Unknown":
                                    return normalized
                    except AttributeError:
                        pass
                    except TypeError:
                        pass
    except Exception as e:
        logger.debug(f"Failed to infer return type for {func_name.name}: {e}")

    return "Unknown"
