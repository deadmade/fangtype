"""Bounded fixpoint pass refining param/return types from call sites, complementing Jedi."""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from fangtype.analysis.ast_traversal import iter_qualified_function_nodes, set_parent_refs
from fangtype.analysis.types import Scope, ScopeTree, TypeInfo, TypeSource
from fangtype.inference.type_utils import normalize_type_name, simplify_union_type

if TYPE_CHECKING:
    from fangtype.cancellation import CancellationToken
    from fangtype.protocols.type_probe_protocol import TypeProbe

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CallableTarget:
    """Resolved callable target for call-flow propagation."""

    kind: str  # "function_ref" | "lambda_ref"
    qualified_name: str | None = None
    return_type_hint: str | None = None


def propagate_call_flow_types(
    tree: ast.Module,
    scope_tree: ScopeTree,
    probe: TypeProbe,
    cancel_token: CancellationToken | None = None,
) -> None:
    """Refine param/return types from call sites; cancel stops early, applied updates persist."""
    set_parent_refs(tree)

    function_nodes = _build_function_node_map(tree)
    function_scopes = {
        scope.get_qualified_name(): scope for scope in scope_tree.get_all_function_scopes()
    }
    class_bases = _build_class_bases(tree)
    if cancel_token is not None and cancel_token.cancelled():
        return
    alias_map = _build_alias_map(tree, scope_tree, function_scopes, probe)

    if not function_nodes or not function_scopes:
        return

    # Call sites/caller scopes are iteration-invariant; resolve once (ast.walk order, lineno-1).
    call_sites: list[tuple[ast.Call, Scope]] = [
        (node, scope_tree.find_scope_for_line(node.lineno - 1))
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    ]

    # Return statements are iteration-invariant (only resolved types change), so collect them once.
    return_nodes_by_function: dict[str, list[ast.Return]] = {}
    for qualified_name, func_node in function_nodes.items():
        collector = _ReturnCollector()
        collector.visit(func_node)
        return_nodes_by_function[qualified_name] = collector.returns

    max_iter = max(3, len(function_scopes) * 2)
    known_param_callables: dict[tuple[str, str], set[CallableTarget]] = {}
    for _ in range(max_iter):
        if cancel_token is not None and cancel_token.cancelled():
            break
        changed = False

        param_types, param_callables = _collect_call_bindings(
            call_sites=call_sites,
            probe=probe,
            function_scopes=function_scopes,
            function_nodes=function_nodes,
            alias_map=alias_map,
            class_bases=class_bases,
            known_param_callables=known_param_callables,
        )
        known_param_callables = _merge_param_callable_maps(known_param_callables, param_callables)

        changed |= _apply_parameter_updates(
            function_scopes, function_nodes, param_types, param_callables
        )
        changed |= _apply_return_updates(
            probe=probe,
            function_scopes=function_scopes,
            function_nodes=function_nodes,
            alias_map=alias_map,
            class_bases=class_bases,
            param_callables=param_callables,
            return_nodes_by_function=return_nodes_by_function,
        )

        if not changed:
            break


def _build_function_node_map(tree: ast.Module) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    # ponytail: same-name defs in one scope collapse (dict keeps the last), as with a top-level
    # redefinition. Now also covers same-name defs in mutually-exclusive branches (try/except
    # import fallbacks), which usually share a signature so the collision is benign.
    return dict(iter_qualified_function_nodes(tree.body))


def _build_class_bases(tree: ast.Module) -> dict[str, list[str]]:
    bases: dict[str, list[str]] = {}

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        names: list[str] = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                names.append(base.id)
            elif isinstance(base, ast.Attribute):
                names.append(base.attr)
        bases[node.name] = names

    return bases


def _build_alias_map(
    tree: ast.Module,
    scope_tree: ScopeTree,
    function_scopes: dict[str, Scope],
    probe: TypeProbe,
) -> dict[tuple[str, str], set[CallableTarget]]:
    alias_map: dict[tuple[str, str], set[CallableTarget]] = {}

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue

        target_name = node.targets[0].id
        scope = scope_tree.find_scope_for_line(node.lineno - 1)
        scope_id = scope.scope_id
        resolved = _resolve_callable_targets(
            node.value,
            scope,
            alias_map,
            function_scopes,
            {},
            probe,
            {},
        )
        if resolved:
            alias_map[(scope_id, target_name)] = resolved

    return alias_map


def _collect_call_bindings(
    call_sites: list[tuple[ast.Call, Scope]],
    probe: TypeProbe,
    function_scopes: dict[str, Scope],
    function_nodes: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    alias_map: dict[tuple[str, str], set[CallableTarget]],
    class_bases: dict[str, list[str]],
    known_param_callables: dict[tuple[str, str], set[CallableTarget]],
) -> tuple[dict[tuple[str, str], set[str]], dict[tuple[str, str], set[CallableTarget]]]:
    param_types: dict[tuple[str, str], set[str]] = {}
    param_callables: dict[tuple[str, str], set[CallableTarget]] = {}

    for node, caller_scope in call_sites:
        active_param_callables = _merge_param_callable_maps(known_param_callables, param_callables)
        targets = _resolve_callable_targets(
            node.func,
            caller_scope,
            alias_map,
            function_scopes,
            active_param_callables,
            probe,
            class_bases,
        )

        for target in targets:
            if target.kind != "function_ref" or not target.qualified_name:
                continue
            if (
                target.qualified_name not in function_scopes
                or target.qualified_name not in function_nodes
            ):
                continue

            func_scope = function_scopes[target.qualified_name]
            func_node = function_nodes[target.qualified_name]
            bindings = _bind_call_arguments(func_node, node)
            for param_name, arg_expr in bindings.items():
                key = (func_scope.scope_id, param_name)
                callables = _resolve_callable_targets(
                    arg_expr,
                    caller_scope,
                    alias_map,
                    function_scopes,
                    active_param_callables,
                    probe,
                    class_bases,
                )
                if callables:
                    param_callables.setdefault(key, set()).update(callables)
                    param_types.setdefault(key, set()).add("Callable")
                    continue

                inferred = _infer_expression_type(
                    arg_expr,
                    caller_scope,
                    probe,
                    alias_map,
                    function_scopes,
                    active_param_callables,
                    class_bases,
                )
                if inferred not in ("", "Unknown"):
                    param_types.setdefault(key, set()).add(inferred)

    return param_types, param_callables


def _bind_call_arguments(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
    call_node: ast.Call,
) -> dict[str, ast.expr]:
    mapping: dict[str, ast.expr] = {}
    args = func_node.args
    positional_params = [arg.arg for arg in args.posonlyargs + args.args]
    kwonly_params = [arg.arg for arg in args.kwonlyargs]

    for index, actual in enumerate(call_node.args):
        if isinstance(actual, ast.Starred):
            # Position of everything after a starred expansion is unknowable.
            break
        if index < len(positional_params):
            mapping[positional_params[index]] = actual
        elif args.vararg is not None:
            mapping[args.vararg.arg] = actual

    for kw in call_node.keywords:
        if kw.arg is None:
            continue
        mapping[kw.arg] = kw.value

    for param in kwonly_params:
        if param in mapping:
            continue
        for kw in call_node.keywords:
            if kw.arg == param:
                mapping[param] = kw.value
                break

    return mapping


def _apply_parameter_updates(
    function_scopes: dict[str, Scope],
    function_nodes: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    param_types: dict[tuple[str, str], set[str]],
    param_callables: dict[tuple[str, str], set[CallableTarget]],
) -> bool:
    changed = False

    for qualified_name, scope in function_scopes.items():
        func_node = function_nodes.get(qualified_name)
        if func_node is None:
            continue

        param_nodes = {
            arg.arg: arg
            for arg in (
                func_node.args.posonlyargs
                + func_node.args.args
                + func_node.args.kwonlyargs
                + ([func_node.args.vararg] if func_node.args.vararg else [])
                + ([func_node.args.kwarg] if func_node.args.kwarg else [])
            )
            if arg is not None
        }

        for param_name, param_info in scope.parameters.items():
            key = (scope.scope_id, param_name)
            observed = set(param_types.get(key, set()))
            if key in param_callables:
                observed.add("Callable")
            if not observed:
                continue

            inferred = _join_types(observed)
            if inferred in ("", "Unknown"):
                continue

            if not _should_update(param_info, inferred):
                continue

            # A param with the `= None` default must keep None (a legal argument) in the union.
            if param_info.type_str in ("None", "NoneType") and "None" not in [
                member.strip() for member in inferred.split("|")
            ]:
                inferred = f"{inferred} | None"

            node = param_nodes.get(param_name)
            line = node.lineno - 1 if node and hasattr(node, "lineno") else param_info.line
            col = node.col_offset if node and hasattr(node, "col_offset") else param_info.col
            scope.parameters[param_name] = TypeInfo(
                type_str=inferred,
                source=TypeSource.PARAMETER_USAGE,
                line=line,
                col=col,
            )
            changed = True

    return changed


def _apply_return_updates(
    probe: TypeProbe,
    function_scopes: dict[str, Scope],
    function_nodes: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    alias_map: dict[tuple[str, str], set[CallableTarget]],
    class_bases: dict[str, list[str]],
    param_callables: dict[tuple[str, str], set[CallableTarget]],
    return_nodes_by_function: dict[str, list[ast.Return]],
) -> bool:
    changed = False

    for qualified_name, func_node in function_nodes.items():
        func_scope = function_scopes.get(qualified_name)
        if func_scope is None:
            continue

        returns = return_nodes_by_function.get(qualified_name, [])
        if not returns:
            continue

        candidates: set[str] = set()
        for ret in returns:
            # A bare `return` (no value) contributes "None"; also narrows ret.value to expr below.
            if ret.value is None:
                candidates.add("None")
                continue
            inferred = _infer_expression_type(
                ret.value,
                func_scope,
                probe,
                alias_map,
                function_scopes,
                param_callables,
                class_bases,
            )
            if inferred not in ("", "Unknown"):
                candidates.add(inferred)

        if not candidates:
            continue

        inferred_return = _join_types(candidates)
        if inferred_return in ("", "Unknown"):
            continue

        existing = func_scope.return_type
        if existing is not None and not _should_update(existing, inferred_return):
            continue

        func_scope.return_type = TypeInfo(
            type_str=inferred_return,
            source=TypeSource.RETURN_VALUE,
            line=func_node.lineno - 1,
            col=func_node.col_offset,
        )
        changed = True

    return changed


def _infer_expression_type(
    expr: ast.expr,
    scope: Scope,
    probe: TypeProbe,
    alias_map: dict[tuple[str, str], set[CallableTarget]],
    function_scopes: dict[str, Scope],
    param_callables: dict[tuple[str, str], set[CallableTarget]],
    class_bases: dict[str, list[str]],
) -> str:
    if isinstance(expr, ast.Constant):
        if expr.value is None:
            return "None"
        if expr.value is Ellipsis:
            # type(Ellipsis).__name__ == "ellipsis" is not a defined name; drop it.
            return ""
        return type(expr.value).__name__

    if isinstance(expr, ast.List):
        return "list"
    if isinstance(expr, ast.Dict):
        return "dict"
    if isinstance(expr, ast.Tuple):
        return "tuple"
    if isinstance(expr, ast.Set):
        return "set"
    if isinstance(expr, ast.ListComp):
        return "list"
    if isinstance(expr, ast.DictComp):
        return "dict"
    if isinstance(expr, ast.SetComp):
        return "set"

    if isinstance(expr, ast.Lambda):
        return "Callable"

    if isinstance(expr, ast.Name):
        var_type = scope.get_variable_type_at_line(expr.id, expr.lineno - 1)
        if var_type and var_type.type_str != "Unknown":
            return var_type.type_str
        if (scope.scope_id, expr.id) in param_callables:
            return "Callable"
        aliases = _lookup_alias_targets(scope, expr.id, alias_map)
        if aliases:
            return "Callable"
        return probe.infer_expr_type(expr)

    if isinstance(expr, ast.Call):
        if isinstance(expr.func, ast.Name) and expr.func.id in {"list", "set", "dict", "tuple"}:
            return expr.func.id
        callable_targets = _resolve_callable_targets(
            expr.func,
            scope,
            alias_map,
            function_scopes,
            param_callables,
            probe,
            class_bases,
        )
        return_types: set[str] = set()
        for target in callable_targets:
            if target.kind == "function_ref" and target.qualified_name in function_scopes:
                target_scope = function_scopes[target.qualified_name]
                if target_scope.return_type and target_scope.return_type.type_str != "Unknown":
                    return_types.add(target_scope.return_type.type_str)
            elif target.kind == "lambda_ref" and target.return_type_hint:
                return_types.add(target.return_type_hint)
        if return_types:
            return _join_types(return_types)
        return probe.infer_expr_type(expr)

    return probe.infer_expr_type(expr)


def _resolve_callable_targets(
    expr: ast.AST,
    scope: Scope,
    alias_map: dict[tuple[str, str], set[CallableTarget]],
    function_scopes: dict[str, Scope],
    param_callables: dict[tuple[str, str], set[CallableTarget]],
    probe: TypeProbe,
    class_bases: dict[str, list[str]],
) -> set[CallableTarget]:
    if isinstance(expr, ast.Lambda):
        hint = probe.infer_expr_type(expr.body)
        return {CallableTarget(kind="lambda_ref", return_type_hint=hint)}

    if isinstance(expr, ast.Name):
        aliases = _lookup_alias_targets(scope, expr.id, alias_map)
        if aliases:
            return aliases

        param_key = (scope.scope_id, expr.id)
        if param_key in param_callables:
            return param_callables[param_key]

        if expr.id in function_scopes:
            return {CallableTarget(kind="function_ref", qualified_name=expr.id)}

        return set()

    if isinstance(expr, ast.Attribute):
        target = _resolve_attribute_callable(expr, scope, function_scopes, probe, class_bases)
        return {target} if target else set()

    return set()


def _resolve_attribute_callable(
    expr: ast.Attribute,
    scope: Scope,
    function_scopes: dict[str, Scope],
    probe: TypeProbe,
    class_bases: dict[str, list[str]],
) -> CallableTarget | None:
    method_name = expr.attr

    if isinstance(expr.value, ast.Name):
        if expr.value.id in ("self", "cls") and scope.parent is not None:
            class_name = scope.parent.name
            qn = _find_method_qualified_name(class_name, method_name, function_scopes)
            if qn:
                return CallableTarget(kind="function_ref", qualified_name=qn)

        inferred_obj = probe.infer_expr_type(expr.value)
        class_name = inferred_obj.split(".")[-1]
        qn = _find_method_qualified_name(class_name, method_name, function_scopes)
        if qn:
            return CallableTarget(kind="function_ref", qualified_name=qn)

    if isinstance(expr.value, ast.Call):
        inner = expr.value
        if (
            isinstance(inner.func, ast.Name)
            and inner.func.id == "super"
            and scope.parent is not None
        ):
            class_name = scope.parent.name
            for base in class_bases.get(class_name, []):
                qn = _find_method_qualified_name(base, method_name, function_scopes)
                if qn:
                    return CallableTarget(kind="function_ref", qualified_name=qn)

    return None


def _find_method_qualified_name(
    class_name: str,
    method_name: str,
    function_scopes: dict[str, Scope],
) -> str | None:
    direct = f"{class_name}.{method_name}"
    if direct in function_scopes:
        return direct

    for qn in function_scopes:
        if qn.endswith(f".{class_name}.{method_name}"):
            return qn
    return None


def _lookup_alias_targets(
    scope: Scope,
    name: str,
    alias_map: dict[tuple[str, str], set[CallableTarget]],
) -> set[CallableTarget]:
    current: Scope | None = scope
    while current is not None:
        key = (current.scope_id, name)
        if key in alias_map:
            return alias_map[key]
        current = current.parent

    module_key = ("module", name)
    return alias_map.get(module_key, set())


def _should_update(existing: TypeInfo, inferred: str) -> bool:
    if existing.source == TypeSource.INHERITED:
        # The base-class contract outranks call-site observations.
        return False
    existing_type = existing.type_str
    if existing_type in ("Unknown", "None", "NoneType", "Any"):
        return True
    if existing.source == TypeSource.LITERAL:
        return False
    if inferred == existing_type:
        return False
    # Only refinement replaces a type: parameterizing the base container ("list" -> "list[str]").
    return inferred.startswith(f"{existing_type}[")


def _merge_param_callable_maps(
    left: dict[tuple[str, str], set[CallableTarget]],
    right: dict[tuple[str, str], set[CallableTarget]],
) -> dict[tuple[str, str], set[CallableTarget]]:
    merged = {key: set(value) for key, value in left.items()}
    for key, value in right.items():
        merged.setdefault(key, set()).update(value)
    return merged


def _join_types(types: set[str]) -> str:
    normalized = [normalize_type_name(t) for t in sorted(types) if t and t != "Unknown"]
    if not normalized:
        return "Unknown"
    if len(normalized) == 1:
        return normalized[0]
    return simplify_union_type(" | ".join(normalized))


class _ReturnCollector(ast.NodeVisitor):
    """Collect return statements in one function body only."""

    def __init__(self) -> None:
        self.returns: list[ast.Return] = []
        self._depth = 0

    def visit_Return(self, node: ast.Return) -> None:
        self.returns.append(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if self._depth > 0:
            return
        self._depth += 1
        self.generic_visit(node)
        self._depth -= 1

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if self._depth > 0:
            return
        self._depth += 1
        self.generic_visit(node)
        self._depth -= 1
