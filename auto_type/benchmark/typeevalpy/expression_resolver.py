"""Context-aware expression resolver for benchmark attribute/subscript queries."""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from auto_type.inference import InferenceResult
    from benchmark.typeevalpy.loader import BenchmarkCase


def resolve_expression_type(case: BenchmarkCase, inference_result: InferenceResult) -> str | None:
    """Resolve expression type from scope-tree and AST context.

    This resolver is benchmark-focused and handles common expression forms that
    are hard to infer with a synthetic query alone, especially:
    - self.attribute lookups inside methods
    - subscript element lookups from known container bases
    """
    expr = case.variable_name
    if not expr:
        return None

    if expr.startswith("self."):
        return _resolve_self_attribute(case, inference_result, expr)

    if "[" in expr and expr.endswith("]"):
        return _resolve_subscript(case, inference_result, expr)

    return None


def _resolve_self_attribute(
    case: BenchmarkCase, inference_result: InferenceResult, expr: str
) -> str | None:
    if not case.function_name:
        return None

    func_scope = inference_result.scope_tree.get_function_scope_by_qualified_name(
        case.function_name
    )
    if not func_scope:
        return None

    attr_name = expr.split(".", 1)[1]
    type_info = inference_result.scope_tree.get_attribute_type_for_method_context(
        func_scope, attr_name, case.line_number - 1
    )
    if type_info and type_info.type_str != "Unknown":
        return type_info.type_str

    return None


def _resolve_subscript(
    case: BenchmarkCase, inference_result: InferenceResult, expr: str
) -> str | None:
    try:
        expr_node = ast.parse(expr, mode="eval").body
    except SyntaxError:
        return None
    return _resolve_expression_node_type(case, inference_result, expr_node)


def _resolve_expression_node_type(
    case: BenchmarkCase,
    inference_result: InferenceResult,
    expr_node: ast.AST,
) -> str | None:
    line_0 = case.line_number - 1

    if isinstance(expr_node, ast.Name):
        return _resolve_base_name_type(case, inference_result, expr_node.id, line_0)

    if isinstance(expr_node, ast.Subscript):
        parent_type = _resolve_expression_node_type(case, inference_result, expr_node.value)
        if not parent_type:
            if isinstance(expr_node.value, ast.Name):
                return _resolve_subscript_from_assignment(
                    case.source_code, expr_node.value.id, line_0
                )
            return None
        element_type = _container_element_type(parent_type)
        if element_type is not None:
            return element_type
        if isinstance(expr_node.value, ast.Name):
            return _resolve_subscript_from_assignment(case.source_code, expr_node.value.id, line_0)
        return None

    return None


def _resolve_base_name_type(
    case: BenchmarkCase,
    inference_result: InferenceResult,
    base_name: str,
    line_0: int,
) -> str | None:
    if case.function_name:
        func_scope = inference_result.scope_tree.get_function_scope_by_qualified_name(
            case.function_name
        )
        if func_scope:
            local_type = func_scope.get_variable_type_at_line(base_name, line_0)
            if local_type and local_type.type_str != "Unknown":
                return local_type.type_str

    module_type = inference_result.scope_tree.get_variable_type_at_line(base_name, line_0)
    if module_type and module_type.type_str != "Unknown":
        return module_type.type_str

    return _resolve_subscript_from_assignment(case.source_code, base_name, line_0)


def _container_element_type(type_str: str) -> str | None:
    stripped = type_str.strip()

    if stripped.startswith("list[") and stripped.endswith("]"):
        return stripped[5:-1].strip()

    if stripped.startswith("tuple[") and stripped.endswith("]"):
        inner = stripped[6:-1].strip()
        if "," not in inner:
            return inner
        members = [
            part.strip() for part in inner.split(",") if part.strip() and part.strip() != "..."
        ]
        if not members:
            return None
        if len(set(members)) == 1:
            return members[0]
        return " | ".join(sorted(set(members)))

    if stripped.startswith("dict[") and stripped.endswith("]"):
        inner = stripped[5:-1].strip()
        parts = _split_top_level(inner, ",")
        if len(parts) == 2:
            return parts[1].strip()
        return None

    return None


def _resolve_subscript_from_assignment(source: str, base_name: str, line_0: int) -> str | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    assign = _find_assignment(tree, base_name, line_0)
    if assign is None:
        return None

    # merged_dict = {**d1, **d2}
    if isinstance(assign, ast.Dict):
        value_types: set[str] = set()
        for key, value in zip(assign.keys, assign.values, strict=False):
            if key is None:
                if isinstance(value, ast.Name):
                    nested = _find_assignment(tree, value.id, line_0)
                    if isinstance(nested, ast.Dict):
                        nested_type = _dict_value_type(nested)
                        if nested_type:
                            value_types.add(nested_type)
                continue
            value_type = _literal_type(value)
            if value_type:
                value_types.add(value_type)

        if value_types:
            if len(value_types) == 1:
                return next(iter(value_types))
            return " | ".join(sorted(value_types))

    # a, *b, c = func1, func2, func3, func4
    if (
        isinstance(assign, ast.Tuple)
        and assign.elts
        and all(isinstance(elt, ast.Name) for elt in assign.elts)
    ):
        return "list[Callable]"

    # g = c()
    if isinstance(assign, ast.Call):
        return_type = _infer_simple_call_return(tree, assign.func, line_0)
        if return_type:
            return _container_element_type(return_type) or return_type

    return None


def _find_assignment(tree: ast.Module, name: str, line_0: int) -> ast.expr | None:
    closest_expr: ast.expr | None = None
    closest_line = -1

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        node_line_0 = node.lineno - 1
        if node_line_0 > line_0 or node_line_0 < closest_line:
            continue

        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == name:
                closest_expr = node.value
                closest_line = node_line_0
            elif isinstance(target, ast.Tuple):
                extracted = _extract_starred_target_value(target, node.value, name)
                if extracted is not None:
                    closest_expr = extracted
                    closest_line = node_line_0

    return closest_expr


def _extract_starred_target_value(target: ast.Tuple, value: ast.AST, name: str) -> ast.expr | None:
    if not isinstance(value, ast.Tuple):
        return None

    target_elts = list(target.elts)
    value_elts = list(value.elts)
    if not target_elts:
        return None

    starred_index = next(
        (i for i, elt in enumerate(target_elts) if isinstance(elt, ast.Starred)), None
    )
    if starred_index is None:
        for idx, elt in enumerate(target_elts):
            if isinstance(elt, ast.Name) and elt.id == name and idx < len(value_elts):
                return value_elts[idx]
        return None

    starred = target_elts[starred_index]
    if (
        isinstance(starred, ast.Starred)
        and isinstance(starred.value, ast.Name)
        and starred.value.id == name
    ):
        prefix = starred_index
        suffix = len(target_elts) - starred_index - 1
        end = len(value_elts) - suffix if suffix > 0 else len(value_elts)
        return ast.Tuple(elts=value_elts[prefix:end], ctx=ast.Load())

    return None


def _infer_simple_call_return(tree: ast.Module, func_expr: ast.expr, line_0: int) -> str | None:
    if not isinstance(func_expr, ast.Name):
        return None

    func_name = func_expr.id
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name != func_name or (node.lineno - 1) > line_0:
            continue
        for stmt in node.body:
            if isinstance(stmt, ast.Return) and stmt.value is not None:
                inferred = _literal_type(stmt.value)
                if inferred:
                    return inferred
    return None


def _dict_value_type(node: ast.Dict) -> str | None:
    value_types = {_literal_type(v) for v in node.values if v is not None}
    value_types.discard(None)
    if not value_types:
        return None
    if len(value_types) == 1:
        return next(iter(value_types))
    return " | ".join(sorted(value_types))


def _literal_type(node: ast.AST) -> str | None:
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
        return None
    if isinstance(node, ast.List):
        if not node.elts:
            return "list"
        inner = {_literal_type(elt) for elt in node.elts}
        inner.discard(None)
        if len(inner) == 1:
            return f"list[{next(iter(inner))}]"
        return "list"
    if isinstance(node, ast.Dict):
        value_type = _dict_value_type(node)
        if value_type:
            return f"dict[Any, {value_type}]"
        return "dict"
    if isinstance(node, ast.Name):
        return "Callable"
    return None


def _split_top_level(text: str, delimiter: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for char in text:
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
        if char == delimiter and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    if current:
        parts.append("".join(current))
    return parts
