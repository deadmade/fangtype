"""Conservative fallback type-recovery heuristics used only when primary inference is unknown."""

from __future__ import annotations

import ast


def _literal_annotation(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    if isinstance(node, ast.Constant):
        if node.value is None:
            return "None"
        if isinstance(node.value, bool):
            return "bool"
        if isinstance(node.value, int):
            return "int"
        if isinstance(node.value, float):
            return "float"
        if isinstance(node.value, str):
            return "str"
    return literal_container_annotation(node)


def literal_container_annotation(node: ast.AST) -> str | None:
    """Format a list/dict/set/tuple literal node as an annotation string, else ``None``."""
    if isinstance(node, ast.List):
        element = homogeneous_literal_element_type(node.elts)
        return f"list[{element}]" if element else "list"
    if isinstance(node, ast.Dict):
        keys = [key for key in node.keys if key is not None]
        key_type = homogeneous_literal_element_type(keys) if len(keys) == len(node.keys) else None
        value_type = homogeneous_literal_element_type(node.values)
        if key_type and value_type:
            return f"dict[{key_type}, {value_type}]"
        return "dict"
    if isinstance(node, ast.Set):
        element = homogeneous_literal_element_type(node.elts)
        return f"set[{element}]" if element else "set"
    if isinstance(node, ast.Tuple):
        return "tuple"
    return None


def homogeneous_literal_element_type(elements: list[ast.expr]) -> str | None:
    """The single scalar type shared by all constant literal elements, else ``None`` (bare)."""
    types: set[str] = set()
    for element in elements:
        if not isinstance(element, ast.Constant):
            return None
        element_type = _literal_annotation(element)
        if element_type is None or element_type == "None":
            return None
        types.add(element_type)
    if len(types) == 1:
        return types.pop()
    return None


def _own_returns(
    function_node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[list[ast.Return], bool]:
    """This scope's own returns (stops at nested function/lambda) plus whether it has ``yield``."""
    returns: list[ast.Return] = []
    is_generator = False

    def visit(node: ast.AST) -> None:
        nonlocal is_generator
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            if isinstance(child, ast.Return):
                returns.append(child)
            elif isinstance(child, (ast.Yield, ast.YieldFrom)):
                is_generator = True
            visit(child)

    visit(function_node)
    return returns, is_generator


def recover_return_union_from_node(
    function_node: ast.AST | None,
) -> str | None:
    """PEP-604 union only when ≥2 distinct return types and every path is a literal, else None."""
    if not isinstance(function_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return None

    return_nodes, is_generator = _own_returns(function_node)
    if is_generator or not return_nodes:
        return None

    inferred: set[str] = set()
    for node in return_nodes:
        if node.value is None:
            return None  # bare `return`: partial knowledge — defer entirely
        literal = _literal_annotation(node.value)
        if literal is None:
            return None  # any unrecovered branch — defer (never narrow)
        inferred.add(literal)

    if len(inferred) < 2:
        return None

    if "None" in inferred:
        return " | ".join([*sorted(inferred - {"None"}), "None"])
    return " | ".join(sorted(inferred))
