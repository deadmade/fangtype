"""Fallback type recovery helpers shared by production workflows.

These heuristics are intentionally conservative and are only used when primary
inference data is missing/unknown.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from auto_type.analysis import Scope
    from auto_type.inference.inference_result import InferenceResult


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
    if isinstance(node, ast.List):
        return "list"
    if isinstance(node, ast.Dict):
        return "dict"
    if isinstance(node, ast.Set):
        return "set"
    if isinstance(node, ast.Tuple):
        return "tuple"
    return None


def _extract_numeric_hint(node: ast.AST) -> str | None:
    literal = _literal_annotation(node)
    if literal in {"int", "float", "str"}:
        return literal
    if isinstance(node, ast.BinOp):
        left = _extract_numeric_hint(node.left)
        right = _extract_numeric_hint(node.right)
        if "float" in {left, right}:
            return "float"
        if "int" in {left, right}:
            return "int"
        if "str" in {left, right}:
            return "str"
    return None


def _infer_call_type_from_source(tree: ast.Module, call: ast.Call, line_0: int) -> str | None:
    if isinstance(call.func, ast.Name):
        fn = call.func.id
        builtin_map = {
            "str": "str",
            "int": "int",
            "float": "float",
            "bool": "bool",
            "list": "list",
            "dict": "dict",
            "set": "set",
            "tuple": "tuple",
            "len": "int",
            "sum": "int",
        }
        if fn in builtin_map:
            return builtin_map[fn]
        if fn and fn[0].isupper():
            return fn
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if node.name != fn or (node.lineno - 1) > line_0:
                continue
            for stmt in node.body:
                if isinstance(stmt, ast.Return):
                    inferred = _literal_annotation(stmt.value)
                    if inferred is not None:
                        return inferred
        return None
    if isinstance(call.func, ast.Attribute) and call.func.attr in {
        "pop",
        "split",
        "keys",
        "values",
        "items",
    }:
        mapping = {
            "pop": "str",
            "split": "list[str]",
            "keys": "list",
            "values": "list",
            "items": "list[tuple]",
        }
        return mapping.get(call.func.attr)
    return None


def _extract_target_value_from_sequence(
    target: ast.Tuple | ast.List,
    value: ast.AST,
    name: str,
) -> ast.AST | None:
    def contains_name(node: ast.AST) -> bool:
        if isinstance(node, ast.Name):
            return node.id == name
        if isinstance(node, ast.Tuple | ast.List):
            return any(contains_name(elt) for elt in node.elts)
        if isinstance(node, ast.Starred):
            return contains_name(node.value)
        return False

    if isinstance(value, ast.GeneratorExp):
        return value if contains_name(target) else None

    if not isinstance(value, ast.Tuple | ast.List):
        return None

    target_elts = list(target.elts)
    value_elts = list(value.elts)
    if not target_elts:
        return None

    starred_index = next(
        (i for i, elt in enumerate(target_elts) if isinstance(elt, ast.Starred)),
        None,
    )
    if starred_index is None:
        for i, elt in enumerate(target_elts):
            if isinstance(elt, ast.Name) and elt.id == name and i < len(value_elts):
                return value_elts[i]
            if isinstance(elt, ast.Tuple | ast.List) and i < len(value_elts):
                nested = _extract_target_value_from_sequence(elt, value_elts[i], name)
                if nested is not None:
                    return nested
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
        return ast.List(elts=value_elts[prefix:end], ctx=ast.Load())
    return None


def _find_assigned_expression(tree: ast.Module, name: str, line_0: int) -> ast.AST | None:
    best_expr: ast.AST | None = None
    best_line = -1

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            node_line_0 = node.lineno - 1
            if node_line_0 > line_0 or node_line_0 < best_line:
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    best_expr = node.value
                    best_line = node_line_0
                    continue
                if isinstance(target, ast.Tuple | ast.List):
                    nested = _extract_target_value_from_sequence(target, node.value, name)
                    if nested is not None:
                        best_expr = nested
                        best_line = node_line_0
        elif isinstance(node, ast.AugAssign | ast.NamedExpr):
            node_line_0 = node.lineno - 1
            if node_line_0 > line_0 or node_line_0 < best_line:
                continue
            if isinstance(node.target, ast.Name) and node.target.id == name:
                best_expr = node.value
                best_line = node_line_0

    return best_expr


def recover_variable_type(
    source: str,
    variable_name: str,
    line_1: int,
    inference_result: InferenceResult,
) -> str | None:
    """Recover variable type from local AST patterns."""
    line_0 = max(line_1 - 1, 0)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    expr = _find_assigned_expression(tree, variable_name, line_0)
    if expr is None:
        return None

    inferred_literal = _literal_annotation(expr)
    if inferred_literal is not None:
        return inferred_literal

    if isinstance(expr, ast.Name):
        local = inference_result.scope_tree.get_variable_type_at_line(expr.id, line_0)
        if local and local.type_str != "Unknown":
            return local.type_str
        nested_expr = _find_assigned_expression(tree, expr.id, line_0)
        if nested_expr is not None and not (
            isinstance(nested_expr, ast.Name) and nested_expr.id == expr.id
        ):
            nested_literal = _literal_annotation(nested_expr)
            if nested_literal is not None:
                return nested_literal
            if isinstance(nested_expr, ast.Call):
                return _infer_call_type_from_source(tree, nested_expr, line_0)
            if isinstance(nested_expr, ast.GeneratorExp):
                nested_gen = _literal_annotation(nested_expr.elt)
                if nested_gen is not None:
                    return nested_gen
                if isinstance(nested_expr.elt, ast.BinOp):
                    return "int"
            if isinstance(nested_expr, ast.ListComp):
                nested_item = _literal_annotation(nested_expr.elt)
                if nested_item is not None:
                    return f"list[{nested_item}]"
                return "list"
        return None

    if isinstance(expr, ast.BinOp):
        if isinstance(expr.op, ast.Add | ast.Sub | ast.Mult | ast.Div | ast.Pow):
            left = _literal_annotation(expr.left)
            right = _literal_annotation(expr.right)
            if "float" in {left, right}:
                return "float"
            if "int" in {left, right}:
                return "int"
        return None

    if isinstance(expr, ast.Call):
        return _infer_call_type_from_source(tree, expr, line_0)

    if isinstance(expr, ast.GeneratorExp):
        gen_inferred = _literal_annotation(expr.elt)
        if gen_inferred:
            return gen_inferred
        if isinstance(expr.elt, ast.BinOp):
            return "int"
        return None

    if isinstance(expr, ast.ListComp):
        element = _literal_annotation(expr.elt)
        if element is not None:
            return f"list[{element}]"
        return "list"

    return None


def _find_function_node_by_name(
    source: str, function_name: str
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    simple = function_name.split(".")[-1]
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    candidates = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == simple
    ]
    return candidates[0] if candidates else None


def _infer_types_from_function_calls(
    tree: ast.Module, function_name: str, parameter_index: int
) -> set[str]:
    inferred: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == function_name
            and parameter_index < len(node.args)
        ):
            typ = _literal_annotation(node.args[parameter_index])
            if typ:
                inferred.add(typ)
    return inferred


def recover_function_return_type(
    source: str,
    function_name: str,
) -> str | None:
    """Recover function return type from AST return statements."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    function_node = _find_function_node_by_name(source, function_name)
    if function_node is None:
        return None

    inferred: set[str] = set()
    has_return_statement = False
    for node in ast.walk(function_node):
        if not isinstance(node, ast.Return):
            continue
        has_return_statement = True
        literal = _literal_annotation(node.value)
        if literal is not None:
            inferred.add(literal)
        elif isinstance(node.value, ast.Name) and node.value.id and node.value.id[0].isupper():
            inferred.add(node.value.id)
        elif isinstance(node.value, ast.Name):
            params = [*function_node.args.posonlyargs, *function_node.args.args]
            for idx, param in enumerate(params):
                if param.arg == node.value.id:
                    call_types = _infer_types_from_function_calls(tree, function_node.name, idx)
                    if call_types:
                        inferred.add(" | ".join(sorted(call_types)))
                        break
        elif isinstance(node.value, ast.BinOp):
            inferred_bin = _extract_numeric_hint(node.value)
            if inferred_bin is not None:
                inferred.add(inferred_bin)

    if not has_return_statement:
        return "None"
    if not inferred:
        return None
    if len(inferred) == 1:
        return next(iter(inferred))
    return " | ".join(sorted(inferred))


def _find_lambda_for_param(source: str, param_name: str, line_number_1: int) -> ast.Lambda | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    candidates: list[ast.Lambda] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Lambda):
            continue
        names = [arg.arg for arg in node.args.args]
        if param_name in names:
            candidates.append(node)

    if not candidates:
        return None

    target_line = max(line_number_1, 1)

    def _get_distance(n: ast.Lambda) -> int:
        line_attr = getattr(n, "lineno", target_line)
        line_val: int = cast(int, line_attr) if isinstance(line_attr, int) else target_line
        return abs(line_val - target_line)

    return min(candidates, key=_get_distance)


def _infer_parameter_type_from_lambda(node: ast.Lambda, param_name: str) -> str | None:
    if (
        isinstance(node.body, ast.Call)
        and isinstance(node.body.func, ast.Name)
        and node.body.func.id == param_name
    ):
        return "Callable"
    if isinstance(node.body, ast.BinOp):
        return _extract_numeric_hint(node.body)
    if isinstance(node.body, ast.UnaryOp):
        return _extract_numeric_hint(node.body.operand)
    return None


def _infer_parameter_type_from_function_usage(
    function_node: ast.FunctionDef | ast.AsyncFunctionDef, param_name: str
) -> str | None:
    for node in ast.walk(function_node):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == param_name
        ):
            return "Callable"

    for node in ast.walk(function_node):
        if not isinstance(node, ast.BinOp):
            continue
        left_is_param = isinstance(node.left, ast.Name) and node.left.id == param_name
        right_is_param = isinstance(node.right, ast.Name) and node.right.id == param_name
        if not (left_is_param or right_is_param):
            continue
        counterpart = node.right if left_is_param else node.left
        return _extract_numeric_hint(counterpart)

    return None


def recover_function_param_type(
    source: str,
    function_name: str,
    parameter_name: str,
    line_number_1: int,
) -> str | None:
    """Recover parameter type from defaults, usage, and call-sites."""
    if function_name == "lambda":
        lambda_node = _find_lambda_for_param(source, parameter_name, line_number_1)
        if lambda_node is None:
            return None
        return _infer_parameter_type_from_lambda(lambda_node, parameter_name)

    try:
        module = ast.parse(source)
    except SyntaxError:
        return None

    simple_name = function_name.split(".")[-1]
    candidates = [
        node
        for node in ast.walk(module)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == simple_name
    ]
    if not candidates:
        return None

    function_node = candidates[0]
    usage_inferred = _infer_parameter_type_from_function_usage(function_node, parameter_name)
    if usage_inferred is not None:
        return usage_inferred

    args = function_node.args
    if args.vararg is not None and args.vararg.arg == parameter_name:
        return "tuple[object, ...]"
    if args.kwarg is not None and args.kwarg.arg == parameter_name:
        return "dict[str, object]"

    positional = [*args.posonlyargs, *args.args]
    if args.defaults:
        defaulted = positional[-len(args.defaults) :]
        for parameter, default in zip(defaulted, args.defaults, strict=False):
            if parameter.arg != parameter_name:
                continue
            inferred = _literal_annotation(default)
            if inferred is not None:
                return inferred

    for kw_parameter, kw_default in zip(args.kwonlyargs, args.kw_defaults, strict=False):
        if kw_parameter.arg != parameter_name:
            continue
        inferred = _literal_annotation(kw_default)
        if inferred is not None:
            return inferred

    all_params = [*args.posonlyargs, *args.args]
    for idx, parameter in enumerate(all_params):
        if parameter.arg != parameter_name:
            continue
        call_types = _infer_types_from_function_calls(module, function_node.name, idx)
        if call_types:
            if len(call_types) == 1:
                return next(iter(call_types))
            return " | ".join(sorted(call_types))

    lowered_name = parameter_name.lower()
    if lowered_name in {"f", "fn", "func", "wrapper", "decorator"}:
        return "Callable"
    if lowered_name in {"cls", "klass"}:
        return "type"

    if any(token in function_name.lower() for token in ("dec", "decorator")):
        return "Callable"

    return None


def resolve_function_scope(inference_result: InferenceResult, function_name: str) -> Scope | None:
    """Resolve function scope by qualified name with tolerant fallbacks."""
    scope = inference_result.scope_tree.get_function_scope_by_qualified_name(function_name)
    if scope is not None:
        return scope

    simple_name = function_name.split(".")[-1]
    candidates = [
        s for s in inference_result.scope_tree.get_all_function_scopes() if s.name == simple_name
    ]
    if len(candidates) == 1:
        return candidates[0]

    suffix_candidates = [
        s
        for s in inference_result.scope_tree.get_all_function_scopes()
        if s.get_qualified_name().endswith(function_name)
    ]
    if len(suffix_candidates) == 1:
        return suffix_candidates[0]

    return None


def find_assignment_target_name_at_line(source: str, line_1: int) -> str | None:
    """Find a concrete assignment target name on an exact line."""

    def _first_assignable_name(target: ast.AST) -> str | None:
        if isinstance(target, ast.Name):
            return target.id
        if isinstance(target, ast.Attribute):
            return ast.unparse(target)
        if isinstance(target, ast.Tuple | ast.List):
            for element in target.elts:
                name = _first_assignable_name(element)
                if name is not None:
                    return name
        if isinstance(target, ast.Starred):
            return _first_assignable_name(target.value)
        return None

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if node.lineno != line_1:
            continue
        for target in node.targets:
            name = _first_assignable_name(target)
            if name is not None:
                return name
    return None


def find_enclosing_function_for_line(
    source: str, line_1: int
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Find the innermost function enclosing a line number."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

        candidates: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue

            lineno = int(node.lineno)
            end_lineno_attr = getattr(node, "end_lineno", lineno)
            end_line: int = int(end_lineno_attr) if isinstance(end_lineno_attr, int) else lineno

            if lineno <= line_1 <= end_line:
                candidates.append(node)
        if not candidates:
            return None

        def _get_lineno(n: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
            return int(n.lineno)

        return max(candidates, key=_get_lineno)
