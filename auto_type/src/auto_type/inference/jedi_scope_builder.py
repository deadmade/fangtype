"""Scope tree building utilities for Jedi inference.

This module provides functions for building hierarchical scope trees from
Jedi inference results.
"""

import ast
import logging
from collections.abc import Sequence
from typing import Any

import jedi

from auto_type.analysis.ast_traversal import set_parent_refs
from auto_type.analysis.types import Scope, ScopeTree, ScopeType, TypeInfo, TypeSource
from auto_type.inference.call_flow_inference import propagate_call_flow_types
from auto_type.inference.jedi_ast_utils import create_ast_node
from auto_type.inference.jedi_type_formatter import (
    extract_type_hint,
    format_types,
    infer_return_type,
)

logger = logging.getLogger(__name__)


def get_scope_name(jedi_name: Any) -> str | None:
    """Get scope name from Jedi Name object.

    Args:
        jedi_name: Jedi Name object

    Returns:
        Scope name string or None for module scope
    """
    if jedi_name is None or jedi_name.type == "module":
        return None
    return str(jedi_name.name)


def get_scope_key(scope: Scope) -> str:
    """Get a string key for a scope.

    Args:
        scope: Scope object

    Returns:
        String key representing the scope path
    """
    if scope.scope_type == ScopeType.MODULE:
        return "module"
    if scope.parent and scope.parent.scope_type != ScopeType.MODULE:
        return f"{get_scope_key(scope.parent)}.{scope.name}"
    return scope.name


def find_parent_scope(
    parent_jedi: Any,
    scope_map: dict[tuple[str | None, str], Scope],
    module_scope: Scope,
) -> Scope:
    """Find the parent scope for a Jedi name.

    Args:
        parent_jedi: Parent Jedi name object
        scope_map: Mapping of scope keys to Scope objects
        module_scope: The root module scope

    Returns:
        Parent Scope object
    """
    if parent_jedi is None or parent_jedi.type == "module":
        return module_scope

    grandparent = parent_jedi.parent()
    grandparent_name = get_scope_name(grandparent)
    parent_key = (grandparent_name, parent_jedi.name)

    return scope_map.get(parent_key, module_scope)


def build_scope_tree(script: jedi.Script, tree: ast.Module) -> ScopeTree:
    """Build hierarchical scope tree using Jedi API.

    Args:
        script: Jedi Script object
        tree: AST Module node
        names: List of Jedi Name objects

    Returns:
        ScopeTree containing all scopes and their types
    """

    # Create module scope (root)
    module_scope = Scope(
        scope_id="module",
        scope_type=ScopeType.MODULE,
        name="<module>",
        ast_node=tree,
    )
    scope_tree = ScopeTree(root=module_scope)
    scope_tree.add_scope(module_scope)

    names = list(script.get_names(all_scopes=True, definitions=True, references=False))
    if not names:
        logger.warning("No names provided to build scope tree")
        return scope_tree

    # Build AST node map for proper line ranges
    ast_node_map: dict[tuple[int, str], ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            ast_node_map[(node.lineno, node.name)] = node

    # Maps to track scopes
    scope_map: dict[tuple[str | None, str], Scope] = {(None, "<module>"): module_scope}

    # First pass: Create all function and class scopes
    for name in names:
        if name.type not in ("function", "class"):
            continue

        parent_scope = find_parent_scope(name.parent(), scope_map, module_scope)

        scope_type = ScopeType.FUNCTION if name.type == "function" else ScopeType.CLASS
        scope_id_prefix = "func" if name.type == "function" else "class"

        parent_key = get_scope_key(parent_scope)
        scope_id = f"{scope_id_prefix}:{parent_key}.{name.name}"

        # Try to get real AST node
        ast_key = (name.line, name.name) if name.line else (1, name.name)
        real_ast_node = ast_node_map.get(ast_key)
        if real_ast_node is None and name.line is None:
            # Fallback: match by name when Jedi does not provide line info.
            candidates = [
                node for (_, node_name), node in ast_node_map.items() if node_name == name.name
            ]
            if candidates:
                real_ast_node = candidates[0]
        ast_node = real_ast_node if real_ast_node is not None else create_ast_node(name)

        new_scope = Scope(
            scope_id=scope_id,
            scope_type=scope_type,
            name=name.name,
            ast_node=ast_node,
            parent=parent_scope,
        )

        scope_tree.add_scope(new_scope)
        parent_scope.children.append(new_scope)

        scope_key = (get_scope_name(name.parent()), name.name)
        scope_map[scope_key] = new_scope

    # Second pass: Add variables, parameters, and infer types
    for name in names:
        parent_scope = find_parent_scope(name.parent(), scope_map, module_scope)

        if name.type == "param":
            try:
                inferences = list(name.infer())
            except Exception as e:
                logger.debug(f"Failed to infer param '{name.name}': {e}")
                inferences = []
            type_str = extract_type_hint(name, inferences) or format_types(inferences)
            type_info = TypeInfo(
                type_str=type_str,
                source=TypeSource.LITERAL,
                line=name.line - 1,
                col=name.column,
            )
            parent_scope.add_parameter(name.name, type_info)

        elif name.type == "statement":
            try:
                inferences = list(name.infer())
            except Exception as e:
                logger.debug(f"Failed to infer statement '{name.name}': {e}")
                inferences = []
            # Check for callable first before extracting type hint
            if any(inf.type == "function" for inf in inferences):
                type_str = "Callable"
            else:
                type_str = extract_type_hint(name, inferences) or format_types(inferences)
            type_info = TypeInfo(
                type_str=type_str,
                source=TypeSource.LITERAL,
                line=(name.line - 1) if name.line is not None else 0,
                col=name.column if name.column is not None else 0,
                ast_node=None,
            )
            parent_scope.add_variable(name.name, type_info)

        elif name.type == "function":
            scope_key = (get_scope_name(name.parent()), name.name)
            if scope_key in scope_map:
                func_scope = scope_map[scope_key]
                return_type_str = infer_return_type(name)
                ast_fallback = _infer_return_type_from_ast_node(func_scope.ast_node)
                if ast_fallback and not return_type_str.startswith(ast_fallback):
                    return_type_str = ast_fallback
                if return_type_str and return_type_str != "Unknown":
                    func_scope.return_type = TypeInfo(
                        type_str=return_type_str,
                        source=TypeSource.RETURN_VALUE,
                        line=(name.line - 1) if name.line is not None else 0,
                        col=name.column if name.column is not None else 0,
                        ast_node=None,
                    )

    # Third pass: Propagate types through call-flow for higher-order calls
    propagate_call_flow_types(tree, scope_tree, script)

    # Fourth pass: Refine assignment types from function call return values
    _infer_function_call_assignments(tree, scope_tree, script)

    # Fifth pass: Extract self.attribute assignments from AST
    _extract_attributes(tree, scope_tree, scope_map, module_scope, script)

    logger.info("Scope tree built: %d scopes", len(scope_tree.scopes_by_id))
    return scope_tree


def _infer_return_type_from_ast_node(func_node: ast.AST | None) -> str | None:
    """Infer return type from AST return statements for common collection literals."""
    if not isinstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return None

    return_types: set[str] = set()

    for node in ast.walk(func_node):
        if not isinstance(node, ast.Return) or node.value is None:
            continue

        value = node.value
        if isinstance(value, (ast.List, ast.ListComp)):
            return_types.add("list")
        elif isinstance(value, (ast.Set, ast.SetComp)):
            return_types.add("set")
        elif isinstance(value, (ast.Dict, ast.DictComp)):
            return_types.add("dict")
        elif isinstance(value, ast.Tuple):
            return_types.add("tuple")
        elif isinstance(value, ast.Call):
            if isinstance(value.func, ast.Name) and value.func.id in {
                "list",
                "set",
                "dict",
                "tuple",
            }:
                return_types.add(value.func.id)

    if len(return_types) == 1:
        return return_types.pop()

    return None


def _infer_function_call_assignments(
    tree: ast.Module,
    scope_tree: ScopeTree,
    script: jedi.Script,
) -> None:
    """Infer variable types for assignments where RHS is a function call.

    This augments Jedi's statement inference for patterns like ``x = foo()`` and
    ``x = obj.method()`` where the assignment may otherwise end up as Unknown/None.

    Args:
        tree: AST Module node
        scope_tree: Built scope tree to update with inferred call return types
        script: Jedi Script used for positional inference at call sites
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue

        assign_line_0 = node.lineno - 1
        inferred_type = _infer_call_return_type(script, node.value)
        ast_fallback_type = _infer_call_return_type_from_ast(tree, node.value, assign_line_0)
        if ast_fallback_type not in ("Unknown", "") and (
            isinstance(node.value.func, ast.Subscript) or inferred_type in ("Unknown", "")
        ):
            inferred_type = ast_fallback_type
        if inferred_type in ("Unknown", ""):
            continue

        target_scope = scope_tree.find_scope_for_line(assign_line_0)
        for target, target_type in _map_assign_targets_to_types(node.targets, inferred_type):
            existing = target_scope.get_variable_type_at_line(target.id, assign_line_0)
            if existing and existing.type_str not in ("Unknown", "None", "NoneType"):
                continue

            target_scope.add_variable(
                target.id,
                TypeInfo(
                    type_str=target_type,
                    source=TypeSource.FUNCTION_CALL,
                    line=assign_line_0,
                    col=target.col_offset,
                    ast_node=node.value,
                ),
            )


def _extract_name_targets(target: ast.AST) -> list[ast.Name]:
    """Extract Name targets from assignment target nodes.

    Args:
        target: Assignment target node

    Returns:
        Flattened list of Name nodes for simple/chained unpacking targets
    """
    if isinstance(target, ast.Name):
        return [target]

    if isinstance(target, ast.Tuple | ast.List):
        names: list[ast.Name] = []
        for element in target.elts:
            names.extend(_extract_name_targets(element))
        return names

    return []


def _map_assign_targets_to_types(
    targets: Sequence[ast.AST],
    inferred_type: str,
) -> list[tuple[ast.Name, str]]:
    """Map assignment targets to type strings, handling unpacking targets."""
    if len(targets) != 1:
        mapped: list[tuple[ast.Name, str]] = []
        for target in targets:
            for name_target in _extract_name_targets(target):
                mapped.append((name_target, inferred_type))
        return mapped

    target = targets[0]
    if not isinstance(target, ast.Tuple | ast.List):
        return [(name_target, inferred_type) for name_target in _extract_name_targets(target)]

    unpack_targets: list[ast.Name] = []
    for element in target.elts:
        if isinstance(element, ast.Name):
            unpack_targets.append(element)
        elif isinstance(element, ast.Starred) and isinstance(element.value, ast.Name):
            unpack_targets.append(element.value)

    if not unpack_targets:
        return []

    # For tuple/list returns, distribute element type when possible.
    element_type = _container_element_type(inferred_type) or inferred_type
    mapped = []
    for name_target in unpack_targets:
        target_type = inferred_type if _is_starred_target(target, name_target.id) else element_type
        mapped.append((name_target, target_type))
    return mapped


def _is_starred_target(target: ast.Tuple | ast.List, name: str) -> bool:
    for element in target.elts:
        if (
            isinstance(element, ast.Starred)
            and isinstance(element.value, ast.Name)
            and element.value.id == name
        ):
            return True
    return False


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

    return None


def _infer_call_return_type(script: jedi.Script, call: ast.Call) -> str:
    """Infer function call return type with positional Jedi inference.

    Jedi most reliably resolves call return types at the end of the call
    expression (typically the closing parenthesis), so we try that first and
    then fall back to the call start.

    Args:
        script: Jedi Script instance
        call: AST Call node to infer

    Returns:
        Inferred type string or "Unknown"
    """
    inference_points = [
        (call.end_lineno or call.lineno, max((call.end_col_offset or 1) - 1, 0)),
        (call.lineno, call.col_offset),
    ]

    for line, col in inference_points:
        try:
            inferences = script.infer(line, col)
        except Exception as e:
            logger.debug(f"Failed call inference at {line}:{col}: {e}")
            continue

        type_str = format_types(list(inferences))
        if type_str not in ("", "Unknown"):
            return type_str

    return "Unknown"


def _infer_call_return_type_from_ast(tree: ast.Module, call: ast.Call, line_0: int) -> str:
    """Infer call return type from local AST when Jedi cannot resolve."""
    callable_name = _resolve_callable_name(tree, call.func, line_0)
    if callable_name is None:
        return "Unknown"
    return _infer_local_function_return_type(tree, callable_name, line_0)


def _resolve_callable_name(tree: ast.Module, expr: ast.expr, line_0: int) -> str | None:
    if isinstance(expr, ast.Name):
        resolved = _resolve_name_assignment_to_callable(tree, expr.id, line_0, set())
        return resolved or expr.id

    if isinstance(expr, ast.Subscript):
        return _resolve_subscript_callable(tree, expr, line_0)

    if isinstance(expr, ast.Attribute):
        # best effort for self.func style references
        return expr.attr

    return None


def _resolve_name_assignment_to_callable(
    tree: ast.Module, name: str, line_0: int, seen: set[str]
) -> str | None:
    if name in seen:
        return None
    seen.add(name)

    assigned = _find_latest_name_assignment(tree, name, line_0)
    if assigned is None:
        return name if _has_function_definition(tree, name, line_0) else None

    if isinstance(assigned, ast.Name):
        return _resolve_name_assignment_to_callable(tree, assigned.id, line_0, seen)

    if isinstance(assigned, ast.Attribute):
        return assigned.attr

    return None


def _resolve_subscript_callable(
    tree: ast.Module, subscript: ast.Subscript, line_0: int
) -> str | None:
    if not isinstance(subscript.value, ast.Name):
        return None

    index = _extract_constant_index(subscript.slice)
    if index is None:
        return None

    assigned = _find_latest_starred_assignment_values(tree, subscript.value.id, line_0)
    if assigned is None or index < 0 or index >= len(assigned):
        return None

    candidate = assigned[index]
    if isinstance(candidate, ast.Name):
        return candidate.id
    if isinstance(candidate, ast.Attribute):
        return candidate.attr
    return None


def _extract_constant_index(slice_node: ast.AST) -> int | None:
    if isinstance(slice_node, ast.Constant) and isinstance(slice_node.value, int):
        return slice_node.value
    return None


def _find_latest_name_assignment(tree: ast.Module, name: str, line_0: int) -> ast.expr | None:
    latest: ast.expr | None = None
    latest_line = -1

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        node_line_0 = node.lineno - 1
        if node_line_0 > line_0 or node_line_0 < latest_line:
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == name:
                latest = node.value
                latest_line = node_line_0

    return latest


def _find_latest_starred_assignment_values(
    tree: ast.Module, starred_name: str, line_0: int
) -> list[ast.expr] | None:
    latest_values: list[ast.expr] | None = None
    latest_line = -1

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        node_line_0 = node.lineno - 1
        if node_line_0 > line_0 or node_line_0 < latest_line:
            continue
        if not isinstance(node.value, ast.Tuple):
            continue

        for target in node.targets:
            if not isinstance(target, ast.Tuple | ast.List):
                continue
            for idx, element in enumerate(target.elts):
                if not isinstance(element, ast.Starred):
                    continue
                if not isinstance(element.value, ast.Name) or element.value.id != starred_name:
                    continue
                prefix = idx
                suffix = len(target.elts) - idx - 1
                end = len(node.value.elts) - suffix if suffix > 0 else len(node.value.elts)
                latest_values = list(node.value.elts[prefix:end])
                latest_line = node_line_0
                break

    return latest_values


def _has_function_definition(tree: ast.Module, name: str, line_0: int) -> bool:
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name == name
            and (node.lineno - 1) <= line_0
        ):
            return True
    return False


def _infer_local_function_return_type(tree: ast.Module, func_name: str, line_0: int) -> str:
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if node.name != func_name or (node.lineno - 1) > line_0:
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.Return) or stmt.value is None:
                continue
            inferred = _infer_literal_type(stmt.value)
            if inferred != "Unknown":
                return inferred
            if isinstance(stmt.value, ast.Name):
                nested = _infer_local_function_return_type(tree, stmt.value.id, line_0)
                if nested != "Unknown":
                    return nested
    return "Unknown"


def _infer_literal_type(node: ast.AST) -> str:
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
        return "Unknown"
    if isinstance(node, ast.List):
        return "list"
    if isinstance(node, ast.Tuple):
        inner = [_infer_literal_type(elt) for elt in node.elts]
        if inner and all(item != "Unknown" for item in inner):
            return f"tuple[{', '.join(inner)}]"
        return "tuple"
    if isinstance(node, ast.Dict):
        return "dict"
    return "Unknown"


def _extract_attributes(
    tree: ast.Module,
    scope_tree: ScopeTree,
    scope_map: dict[tuple[str | None, str], Scope],
    module_scope: Scope,
    script: jedi.Script,
) -> None:
    """Extract self.attribute assignments from AST and add to scopes.

    This function traverses the AST to find attribute assignments like
    `self.width = value` and adds them to the appropriate function scope's
    attributes dictionary.

    Args:
        tree: AST Module node
        scope_tree: The scope tree being built
        scope_map: Mapping of scope keys to Scope objects
        module_scope: The root module scope
        script: Jedi script for call-return inference fallback
    """
    # Build a mapping from (parent_name, func_name) to scope for method lookup
    method_scopes: dict[tuple[str | None, str], Scope] = {}
    for scope in scope_tree.scopes_by_id.values():
        if scope.scope_type == ScopeType.FUNCTION and scope.parent:
            parent_name = scope.parent.name if scope.parent.scope_type == ScopeType.CLASS else None
            method_scopes[(parent_name, scope.name)] = scope

    # Set parent references on AST nodes for proper traversal
    set_parent_refs(tree)

    # Walk the AST to find attribute assignments
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            # Get the scope for this function
            parent: ast.AST | None = getattr(node, "parent", None)
            parent_name = None
            if parent and isinstance(parent, ast.ClassDef):
                parent_name = parent.name

            scope_key = (parent_name, node.name)
            func_scope = method_scopes.get(scope_key)

            if not func_scope:
                # Try to find via scope_map
                func_scope = scope_map.get(scope_key)

            if not func_scope:
                continue

            # Look for self.attribute assignments in the function body
            for stmt in node.body:
                if isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        for target_node, value_node in _iter_assignment_target_value_pairs(
                            target, stmt.value
                        ):
                            for attr_target in _extract_attribute_targets(target_node):
                                _process_attribute_assignment(
                                    attr_target,
                                    value_node,
                                    func_scope,
                                    script,
                                )
                elif isinstance(stmt, ast.AnnAssign):
                    _process_attribute_assignment(stmt.target, stmt.value, func_scope, script)
                elif isinstance(stmt, ast.AugAssign):
                    _process_augmented_attribute_assignment(
                        stmt.target, stmt.value, stmt.op, func_scope, script
                    )


def _process_attribute_assignment(
    target: ast.AST,
    value: ast.AST | None,
    func_scope: Scope,
    script: jedi.Script,
) -> None:
    """Process a single attribute assignment and add to scope.

    Args:
        target: The assignment target (should be Attribute node)
        value: The assigned value (for type inference)
        func_scope: The function scope to add the attribute to
        script: Jedi script for call-return fallback
    """
    if not isinstance(target, ast.Attribute):
        return

    # Check if it's an attribute assignment on a name (e.g., self.attr or obj.attr)
    if isinstance(target.value, ast.Name):
        obj_name = target.value.id
        attr_name = target.attr

        # For self.* attributes, use just the attribute name
        # For other objects, use qualified name like "point.x"
        key = attr_name if obj_name == "self" else f"{obj_name}.{attr_name}"

        # Infer type from the value, resolving names/calls from scope context when possible.
        type_str = _infer_type_from_ast(value, func_scope, script) if value else "Unknown"

        type_info = TypeInfo(
            type_str=type_str,
            source=TypeSource.LITERAL,
            line=target.lineno - 1 if hasattr(target, "lineno") else 0,
            col=target.col_offset if hasattr(target, "col_offset") else 0,
            ast_node=value,
        )

        func_scope.attributes[key] = type_info
        if (
            obj_name == "self"
            and func_scope.parent
            and func_scope.parent.scope_type == ScopeType.CLASS
        ):
            func_scope.parent.attributes[attr_name] = type_info


def _extract_attribute_targets(target: ast.AST) -> list[ast.Attribute]:
    if isinstance(target, ast.Attribute):
        return [target]
    if isinstance(target, ast.Tuple | ast.List):
        result: list[ast.Attribute] = []
        for element in target.elts:
            result.extend(_extract_attribute_targets(element))
        return result
    return []


def _iter_assignment_target_value_pairs(
    target: ast.AST, value: ast.AST | None
) -> list[tuple[ast.AST, ast.AST | None]]:
    """Pair assignment targets with corresponding RHS expressions when possible."""
    if not isinstance(target, ast.Tuple | ast.List):
        return [(target, value)]

    if not isinstance(value, ast.Tuple | ast.List):
        return [(target, value)]

    pairs: list[tuple[ast.AST, ast.AST | None]] = []
    value_index = 0
    for idx, element in enumerate(target.elts):
        if isinstance(element, ast.Starred):
            # Starred target gets grouped remaining items except suffix length.
            suffix_len = len(target.elts) - idx - 1
            end = len(value.elts) - suffix_len if suffix_len > 0 else len(value.elts)
            grouped = ast.List(elts=list(value.elts[value_index:end]), ctx=ast.Load())
            pairs.append((element.value, grouped))
            value_index = end
            continue

        rhs = value.elts[value_index] if value_index < len(value.elts) else None
        pairs.append((element, rhs))
        value_index += 1

    return pairs


def _process_augmented_attribute_assignment(
    target: ast.AST,
    value: ast.AST,
    op: ast.operator,
    func_scope: Scope,
    script: jedi.Script,
) -> None:
    if not isinstance(target, ast.Attribute) or not isinstance(target.value, ast.Name):
        return
    if target.value.id != "self":
        return

    attr_name = target.attr
    existing = func_scope.attributes.get(attr_name)
    if existing is None and func_scope.parent and func_scope.parent.scope_type == ScopeType.CLASS:
        existing = func_scope.parent.attributes.get(attr_name)
    rhs_type = _infer_type_from_ast(value, func_scope, script)
    type_str = _infer_augmented_type(existing.type_str if existing else "Unknown", rhs_type, op)

    type_info = TypeInfo(
        type_str=type_str,
        source=TypeSource.LITERAL,
        line=target.lineno - 1 if hasattr(target, "lineno") else 0,
        col=target.col_offset if hasattr(target, "col_offset") else 0,
        ast_node=value,
    )
    func_scope.attributes[attr_name] = type_info
    if func_scope.parent and func_scope.parent.scope_type == ScopeType.CLASS:
        func_scope.parent.attributes[attr_name] = type_info


def _infer_augmented_type(lhs: str, rhs: str, op: ast.operator) -> str:
    if not isinstance(op, ast.Add):
        return lhs if lhs != "Unknown" else rhs

    if lhs == "str" and rhs == "str":
        return "str"

    numeric = {"int", "float"}
    if lhs in numeric and rhs in numeric:
        if "float" in (lhs, rhs):
            return "float"
        return "int"

    if lhs != "Unknown":
        return lhs
    return rhs


def _infer_name_type(node: ast.Name, func_scope: Scope, line_0_based: int) -> str:
    """Infer type for a Name node using function/module scope lookups."""
    type_info = func_scope.get_variable_type_at_line(node.id, line_0_based)
    if type_info and type_info.type_str != "Unknown":
        return type_info.type_str

    if node.id in func_scope.parameters:
        param_type = func_scope.parameters[node.id].type_str
        if param_type != "Unknown":
            return param_type

    return "Unknown"


def _infer_type_from_ast(
    node: ast.AST | None,
    func_scope: Scope,
    script: jedi.Script,
) -> str:
    """Infer type from an AST node.

    Args:
        node: AST node to infer type from

    Returns:
        String representation of the type
    """
    if node is None:
        return "Unknown"

    if isinstance(node, ast.Constant):
        if node.value is None:
            return "None"
        elif isinstance(node.value, bool):
            return "bool"
        elif isinstance(node.value, int):
            return "int"
        elif isinstance(node.value, float):
            return "float"
        elif isinstance(node.value, str):
            return "str"
        elif isinstance(node.value, bytes):
            return "bytes"
        else:
            return "Unknown"
    elif isinstance(node, ast.List):
        return "list"
    elif isinstance(node, ast.Tuple):
        return "tuple"
    elif isinstance(node, ast.Dict):
        return "dict"
    elif isinstance(node, ast.Set):
        return "set"
    elif isinstance(node, ast.Name):
        line_0_based = node.lineno - 1 if hasattr(node, "lineno") else 0
        return _infer_name_type(node, func_scope, line_0_based)
    elif isinstance(node, ast.Attribute):
        if isinstance(node.value, ast.Name) and node.value.id == "self":
            class_scope = (
                func_scope.parent
                if func_scope.parent and func_scope.parent.scope_type == ScopeType.CLASS
                else None
            )
            if class_scope:
                if any(
                    child.scope_type == ScopeType.FUNCTION and child.name == node.attr
                    for child in class_scope.children
                ):
                    return "Callable"
                class_attr = class_scope.attributes.get(node.attr)
                if class_attr and class_attr.type_str != "Unknown":
                    return class_attr.type_str
            method_attr = func_scope.attributes.get(node.attr)
            if method_attr and method_attr.type_str != "Unknown":
                return method_attr.type_str
        return "Unknown"
    elif isinstance(node, ast.BinOp):
        lhs = _infer_type_from_ast(node.left, func_scope, script)
        rhs = _infer_type_from_ast(node.right, func_scope, script)
        inferred = _infer_augmented_type(lhs, rhs, node.op)
        return inferred if inferred != "" else "Unknown"
    elif isinstance(node, ast.Call):
        return _infer_call_return_type(script, node)
    else:
        return "Unknown"
