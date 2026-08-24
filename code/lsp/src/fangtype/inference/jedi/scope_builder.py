"""Scope tree building utilities for Jedi inference."""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from fangtype.analysis.ast_traversal import set_parent_refs
from fangtype.analysis.types import Scope, ScopeTree, ScopeType, TypeInfo, TypeSource
from fangtype.inference.caching_probe import CachingProbe
from fangtype.inference.call_flow_inference import propagate_call_flow_types
from fangtype.inference.contract_propagation import apply_contract_propagation
from fangtype.inference.jedi.ast_utils import create_ast_node
from fangtype.inference.jedi.positions import script_byte_col_to_codepoint
from fangtype.inference.jedi.probe import JediProbe
from fangtype.inference.jedi.type_formatter import (
    extract_type_hint,
    format_types,
    infer_return_type,
    resolve_import,
)
from fangtype.inference.override_inference import (
    annotation_includes_none,
    apply_override_inference,
)
from fangtype.inference.type_recovery import (
    _own_returns,
    literal_container_annotation,
    recover_return_union_from_node,
)
from fangtype.inference.type_utils import import_for_annotation

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    import jedi

    from fangtype.cancellation import CancellationToken


logger = logging.getLogger(__name__)


class _GlobalNonlocalCollector(ast.NodeVisitor):
    """Collect ``global``/``nonlocal`` names in one scope's own body (not nested scopes)."""

    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_Global(self, node: ast.Global) -> None:
        self.names.update(node.names)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.names.update(node.names)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        pass  # stop at nested scope

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        pass  # stop at nested scope

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        pass  # stop at nested scope

    def visit_Lambda(self, node: ast.Lambda) -> None:
        pass  # stop at nested scope


def collect_declared_global_nonlocal(scope_node: ast.AST) -> set[str]:
    """Names declared ``global``/``nonlocal`` in ``scope_node``'s own body (not nested scopes)."""
    collector = _GlobalNonlocalCollector()
    # Visit children, not the node, so the scope's own def/class isn't skipped by visit_* override.
    for child in ast.iter_child_nodes(scope_node):
        collector.visit(child)
    return collector.names


class _ComprehensionTargetCollector(ast.NodeVisitor):
    """Comprehension loop-target positions in a scope's body (not real bindings; suppressed)."""

    def __init__(self, script: jedi.Script) -> None:
        self._script = script
        self.positions: set[tuple[int, int, str]] = set()

    def _record_generators(
        self, node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp
    ) -> None:
        for generator in node.generators:
            for name_node in ast.walk(generator.target):
                if isinstance(name_node, ast.Name):
                    # Store a code-point col so the suppression key matches TypeInfo.col.
                    col = script_byte_col_to_codepoint(
                        self._script, name_node.lineno, name_node.col_offset
                    )
                    self.positions.add((name_node.lineno - 1, col, name_node.id))

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._record_generators(node)
        self.generic_visit(node)

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._record_generators(node)
        self.generic_visit(node)

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._record_generators(node)
        self.generic_visit(node)

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._record_generators(node)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        pass  # stop at nested scope

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        pass  # stop at nested scope

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        pass  # stop at nested scope

    def visit_Lambda(self, node: ast.Lambda) -> None:
        pass  # stop at nested scope


def collect_comprehension_target_positions(
    scope_node: ast.AST, script: jedi.Script
) -> set[tuple[int, int, str]]:
    """Comprehension loop-target ``(line0,col,name)`` positions in a scope's body (not nested)."""
    collector = _ComprehensionTargetCollector(script)
    # Visit children, not the node, so the scope's own def/class isn't skipped by visit_* override.
    for child in ast.iter_child_nodes(scope_node):
        collector.visit(child)
    return collector.positions


def get_scope_name(jedi_name: Any) -> str | None:
    """Get scope name from a Jedi Name object; None for module scope."""
    if jedi_name is None or jedi_name.type == "module":
        return None
    return str(jedi_name.name)


def get_scope_key(scope: Scope) -> str:
    """Get a string key representing the scope path.

    The def line is part of the key: same-named siblings (a platform-conditional ``def get_path``,
    a ``@property``/``@setter`` pair) share a qualified name, so only position separates them.
    """
    if scope.scope_type == ScopeType.MODULE:
        return "module"
    own = f"{scope.name}@{getattr(scope.ast_node, 'lineno', 0)}"
    if scope.parent and scope.parent.scope_type != ScopeType.MODULE:
        return f"{get_scope_key(scope.parent)}.{own}"
    return own


def safe_parent(name: Any) -> Any:
    """``name.parent()``, or ``None`` when Jedi cannot resolve it.

    Jedi reaches into parso's module-global parse cache through an unguarded
    ``parser_cache[grammar._hashed][path]`` (``jedi/parser_utils.py``), so a name whose
    module has been evicted raises ``KeyError`` from deep inside ``parent()``. Every
    caller here already treats an unresolvable parent as "attach it to module scope", so
    returning ``None`` costs that one name its exact scope instead of costing the whole
    file every type. This mirrors the per-name handling ``name.infer()`` already gets.
    """
    try:
        return name.parent()
    except Exception as e:
        logger.debug("Failed to resolve parent of '%s': %s", getattr(name, "name", "?"), e)
        return None


def find_parent_scope(
    parent_jedi: Any,
    scope_map: dict[tuple[str | None, str, int | None], Scope],
    module_scope: Scope,
) -> Scope:
    """Find the parent Scope for a Jedi name, falling back to the module scope."""
    if parent_jedi is None or parent_jedi.type == "module":
        return module_scope

    grandparent = safe_parent(parent_jedi)
    grandparent_name = get_scope_name(grandparent)
    parent_key = (grandparent_name, parent_jedi.name, parent_jedi.line)

    return scope_map.get(parent_key, module_scope)


def build_scope_tree(
    script: jedi.Script,
    tree: ast.Module,
    *,
    enable_cross_file: bool = True,
    cancel_token: CancellationToken | None = None,
) -> ScopeTree:
    """Build a ScopeTree via Jedi; cancel_token bails later passes, returns partial tree."""

    # Create module scope (root)
    module_scope = Scope(
        scope_id="module",
        scope_type=ScopeType.MODULE,
        name="<module>",
        ast_node=tree,
    )
    module_scope.nonlocal_or_global_names = collect_declared_global_nonlocal(tree)
    module_scope.comprehension_target_positions = collect_comprehension_target_positions(
        tree, script
    )
    scope_tree = ScopeTree(root=module_scope)
    scope_tree.add_scope(module_scope)

    names = list(script.get_names(all_scopes=True, definitions=True, references=False))
    if not names:
        # A module with nothing but comments or a docstring really has no names, and that
        # tree is correct and cacheable. A module with actual statements has names, so
        # Jedi returning none means the analysis failed -- most often a parso parse-cache
        # miss deep inside name resolution. Mark it degraded so DocumentCache refuses it
        # rather than serving the failure until the document is edited.
        substantive = [
            node
            for node in tree.body
            if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))
        ]
        if substantive:
            logger.warning(
                "Jedi returned no names for a module with %d statements; "
                "treating the scope tree as degraded",
                len(substantive),
            )
            scope_tree.degraded = True
        return scope_tree

    # Build AST node map for proper line ranges
    ast_node_map: dict[tuple[int, str], ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            ast_node_map[(node.lineno, node.name)] = node

    # Keyed (parent_name, name, def_line) so same-named siblings stay distinct.
    scope_map: dict[tuple[str | None, str, int | None], Scope] = {
        (None, "<module>", None): module_scope
    }

    # Params with a `= None` default keep a None member (Jedi drops it once call sites give a type).
    none_default_params = _collect_none_default_params(tree)

    # First pass: Create all function and class scopes
    for name in names:
        if name.type not in ("function", "class"):
            continue

        parent_scope = find_parent_scope(safe_parent(name), scope_map, module_scope)

        scope_type = ScopeType.FUNCTION if name.type == "function" else ScopeType.CLASS
        scope_id_prefix = "func" if name.type == "function" else "class"

        parent_key = get_scope_key(parent_scope)
        # `@line` keeps same-named siblings from overwriting each other in scopes_by_id.
        scope_id = f"{scope_id_prefix}:{parent_key}.{name.name}@{name.line}"

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
        new_scope.nonlocal_or_global_names = collect_declared_global_nonlocal(ast_node)
        new_scope.comprehension_target_positions = collect_comprehension_target_positions(
            ast_node, script
        )

        scope_tree.add_scope(new_scope)
        parent_scope.children.append(new_scope)

        scope_key = (get_scope_name(safe_parent(name)), name.name, name.line)
        scope_map[scope_key] = new_scope

    # Second pass: Add variables, parameters, and infer types
    for name in names:
        if cancel_token is not None and cancel_token.cancelled():
            break
        parent_scope = find_parent_scope(safe_parent(name), scope_map, module_scope)

        if name.type == "param":
            try:
                inferences = list(name.infer())
            except Exception as e:
                logger.debug(f"Failed to infer param '{name.name}': {e}")
                inferences = []
            type_str = extract_type_hint(name, inferences) or format_types(inferences)
            if (
                (name.line, str(name.name)) in none_default_params
                and type_str not in ("Unknown", "None", "NoneType")
                and not annotation_includes_none(type_str)
            ):
                type_str = f"{type_str} | None"
            import_hint = (
                resolve_import(inferences[0], script.path, type_str)
                if len(inferences) == 1
                else import_for_annotation(type_str)
            )
            type_info = TypeInfo(
                type_str=type_str,
                source=TypeSource.LITERAL,
                line=name.line - 1,
                col=name.column,
                import_hint=import_hint,
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
            # ponytail: only the top-level concrete type's import is captured; element types
            # inside generics/unions (list[Decimal], dict[str, MyClass]) are not resolved.
            # Upgrade path: per-element Jedi inference on the subscript value if needed.
            import_hint = (
                resolve_import(inferences[0], script.path, type_str)
                if len(inferences) == 1
                else import_for_annotation(type_str)
            )
            type_info = TypeInfo(
                type_str=type_str,
                source=TypeSource.LITERAL,
                line=(name.line - 1) if name.line is not None else 0,
                col=name.column if name.column is not None else 0,
                ast_node=None,
                import_hint=import_hint,
            )
            parent_scope.add_variable(name.name, type_info)

        elif name.type == "function":
            scope_key = (get_scope_name(safe_parent(name)), name.name, name.line)
            if scope_key in scope_map:
                func_scope = scope_map[scope_key]
                return_type_str = infer_return_type(name)
                ast_union = recover_return_union_from_node(func_scope.ast_node)
                if ast_union:
                    # Restore the union Jedi prunes to one type; fires for >=2 all-literal returns.
                    return_type_str = ast_union
                else:
                    ast_fallback = _infer_return_type_from_ast_node(func_scope.ast_node)
                    return_type_str = _apply_ast_return_fallback(return_type_str, ast_fallback)
                if return_type_str and return_type_str != "Unknown":
                    # ponytail: only a synthesised name's import is recoverable here. `name` infers
                    # to the function itself rather than to what it returns, so resolve_import has
                    # nothing to read, and a concrete class returned from another module still
                    # earns no import. Upgrade path: infer the return expression, not the def.
                    func_scope.return_type = TypeInfo(
                        type_str=return_type_str,
                        source=TypeSource.RETURN_VALUE,
                        line=(name.line - 1) if name.line is not None else 0,
                        col=name.column if name.column is not None else 0,
                        ast_node=None,
                        import_hint=import_for_annotation(return_type_str),
                    )

    # Each post-loop pass checks cancel token so a cancelled request bails; <=1 runs after cancel.
    post_loop_passes: list[tuple[Callable[[], None], str]] = [
        (
            lambda: apply_override_inference(script, scope_tree),
            "Inherited-signature refinement: overrides adopt the base-method contract",
        ),
        (
            lambda: apply_contract_propagation(
                script,
                scope_tree,
                enable_cross_file=enable_cross_file,
                cancel_token=cancel_token,
            ),
            "Callable-contract propagation: a dead-end callback returned by name from a "
            "hook override adopts that hook's Callable-contract params. PARAMS ONLY -- "
            "an earlier scoring prototype measured RETURN propagation at 40% wrong on "
            "eligible slots (declared supertype FunctionLike vs actual narrower "
            "CallableType), while param propagation alone measured 0% wrong.",
        ),
        (
            lambda: propagate_call_flow_types(
                tree, scope_tree, CachingProbe(JediProbe(script)), cancel_token=cancel_token
            ),
            "Third pass: Propagate types through call-flow for higher-order calls",
        ),
        (
            lambda: _infer_function_call_assignments(
                tree, scope_tree, script, cancel_token=cancel_token
            ),
            "Fourth pass: Refine assignment types from function call return values",
        ),
        (
            lambda: _extract_attributes(
                tree, scope_tree, scope_map, module_scope, script, cancel_token=cancel_token
            ),
            "Fifth pass: Extract self.attribute assignments from AST",
        ),
    ]
    for pass_callable, _description in post_loop_passes:
        if cancel_token is not None and cancel_token.cancelled():
            return scope_tree
        pass_callable()

    logger.info("Scope tree built: %d scopes", len(scope_tree.scopes_by_id))
    return scope_tree


def _apply_ast_return_fallback(jedi_type_str: str, ast_fallback: str | None) -> str:
    """Reconcile Jedi return type with a bare AST container; keep parameterized hint over bare."""
    if not ast_fallback:
        return jedi_type_str
    if "[" in jedi_type_str:
        return jedi_type_str
    if jedi_type_str.startswith(ast_fallback):
        return jedi_type_str
    return ast_fallback


def _collect_none_default_params(tree: ast.Module) -> set[tuple[int, str]]:
    """Collect (line, name) of params whose default is the ``None`` literal."""
    none_defaults: set[tuple[int, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        positional = [*node.args.posonlyargs, *node.args.args]
        defaults = node.args.defaults
        defaulted = positional[len(positional) - len(defaults) :]
        for arg, default in zip(defaulted, defaults, strict=False):
            if isinstance(default, ast.Constant) and default.value is None:
                none_defaults.add((arg.lineno, arg.arg))
        for arg, kw_default in zip(node.args.kwonlyargs, node.args.kw_defaults, strict=False):
            if isinstance(kw_default, ast.Constant) and kw_default.value is None:
                none_defaults.add((arg.lineno, arg.arg))
    return none_defaults


def _infer_return_type_from_ast_node(func_node: ast.AST | None) -> str | None:
    """Infer return type from AST return statements for common collection literals.

    Mirrors ``recover_return_union_from_node``'s discipline: any return branch this can't
    classify as a recognized container literal -- including a bare ``return`` or
    ``return None`` -- forces a defer (``None``) rather than an unsound narrow guess.
    """
    if not isinstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return None

    return_nodes, is_generator = _own_returns(func_node)
    if is_generator or not return_nodes:
        return None

    return_types: set[str] = set()

    for node in return_nodes:
        value = node.value

        if isinstance(value, (ast.List, ast.ListComp)):
            return_types.add("list")
        elif isinstance(value, (ast.Set, ast.SetComp)):
            return_types.add("set")
        elif isinstance(value, (ast.Dict, ast.DictComp)):
            return_types.add("dict")
        elif isinstance(value, ast.Tuple):
            return_types.add("tuple")
        elif (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id in {"list", "set", "dict", "tuple"}
        ):
            return_types.add(value.func.id)
        else:
            return None  # bare/`return None`/unrecovered branch -- defer (never narrow)

    if len(return_types) == 1:
        return return_types.pop()

    return None


@dataclass(frozen=True)
class _CallSiteIndex:
    """Call-assignment lookup maps, one ``ast.walk`` pass; order fixes tie-breaks byte-exact."""

    # name -> [(line0, assigned_value), ...] in ast.walk order (all Name targets).
    name_assignments: dict[str, list[tuple[int, ast.expr]]]
    # name -> [FunctionDef|AsyncFunctionDef, ...] in ast.walk order.
    func_defs: dict[str, list[ast.FunctionDef | ast.AsyncFunctionDef]]
    # starred-target name -> [(line0, distributed_rhs_values), ...] in ast.walk order.
    starred_assignments: dict[str, list[tuple[int, list[ast.expr]]]]


def _build_call_site_index(tree: ast.Module) -> _CallSiteIndex:
    """Build call-assignment maps in one ``ast.walk`` pass; walk order drives last-write-wins."""
    name_assignments: dict[str, list[tuple[int, ast.expr]]] = {}
    func_defs: dict[str, list[ast.FunctionDef | ast.AsyncFunctionDef]] = {}
    starred_assignments: dict[str, list[tuple[int, list[ast.expr]]]] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            node_line_0 = node.lineno - 1
            # Mirror _find_latest_name_assignment: per Name target in order (shared line/value).
            for target in node.targets:
                if isinstance(target, ast.Name):
                    name_assignments.setdefault(target.id, []).append((node_line_0, node.value))
            # Mirror _find_latest_starred_assignment_values: Tuple RHS, first Name Starred elem.
            if isinstance(node.value, ast.Tuple):
                for target in node.targets:
                    if not isinstance(target, ast.Tuple | ast.List):
                        continue
                    for idx, element in enumerate(target.elts):
                        if not isinstance(element, ast.Starred):
                            continue
                        if not isinstance(element.value, ast.Name):
                            continue
                        prefix = idx
                        suffix = len(target.elts) - idx - 1
                        end = len(node.value.elts) - suffix if suffix > 0 else len(node.value.elts)
                        starred_assignments.setdefault(element.value.id, []).append(
                            (node_line_0, list(node.value.elts[prefix:end]))
                        )
                        break
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            func_defs.setdefault(node.name, []).append(node)

    return _CallSiteIndex(name_assignments, func_defs, starred_assignments)


def _infer_function_call_assignments(
    tree: ast.Module,
    scope_tree: ScopeTree,
    script: jedi.Script,
    cancel_token: CancellationToken | None = None,
) -> None:
    """Infer types for ``x=foo()`` calls Jedi leaves Unknown/None; cancel_token bails mid-walk."""
    call_site_index = _build_call_site_index(tree)
    for node in ast.walk(tree):
        if cancel_token is not None and cancel_token.cancelled():
            break
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue

        assign_line_0 = node.lineno - 1
        inferred_type = _infer_call_return_type(script, node.value)
        ast_fallback_type = _infer_call_return_type_from_ast(
            call_site_index, node.value, assign_line_0
        )
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
                    col=script_byte_col_to_codepoint(script, target.lineno, target.col_offset),
                ),
            )


def _extract_name_targets(target: ast.AST) -> list[ast.Name]:
    """Flatten assignment target nodes into a list of Name nodes (simple/chained unpacking)."""
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
    """Infer a call's return type via Jedi; try call end then start; "Unknown" if none."""
    end_line = call.end_lineno or call.lineno
    end_cp = script_byte_col_to_codepoint(script, end_line, call.end_col_offset or 1)
    start_cp = script_byte_col_to_codepoint(script, call.lineno, call.col_offset)
    inference_points = [
        (end_line, max(end_cp - 1, 0)),
        (call.lineno, start_cp),
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


def _infer_call_return_type_from_ast(index: _CallSiteIndex, call: ast.Call, line_0: int) -> str:
    """Infer call return type from local AST when Jedi cannot resolve."""
    callable_name = _resolve_callable_name(index, call.func, line_0)
    if callable_name is None:
        return "Unknown"
    return _infer_local_function_return_type(index, callable_name, line_0)


def _resolve_callable_name(index: _CallSiteIndex, expr: ast.expr, line_0: int) -> str | None:
    if isinstance(expr, ast.Name):
        resolved = _resolve_name_assignment_to_callable(index, expr.id, line_0, set())
        return resolved or expr.id

    if isinstance(expr, ast.Subscript):
        return _resolve_subscript_callable(index, expr, line_0)

    if isinstance(expr, ast.Attribute):
        # best effort for self.func style references
        return expr.attr

    return None


def _resolve_name_assignment_to_callable(
    index: _CallSiteIndex, name: str, line_0: int, seen: set[str]
) -> str | None:
    if name in seen:
        return None
    seen.add(name)

    assigned = _find_latest_name_assignment(index, name, line_0)
    if assigned is None:
        return name if _has_function_definition(index, name, line_0) else None

    if isinstance(assigned, ast.Name):
        return _resolve_name_assignment_to_callable(index, assigned.id, line_0, seen)

    if isinstance(assigned, ast.Attribute):
        return assigned.attr

    return None


def _resolve_subscript_callable(
    index: _CallSiteIndex, subscript: ast.Subscript, line_0: int
) -> str | None:
    if not isinstance(subscript.value, ast.Name):
        return None

    slice_index = _extract_constant_index(subscript.slice)
    if slice_index is None:
        return None

    assigned = _find_latest_starred_assignment_values(index, subscript.value.id, line_0)
    if assigned is None or slice_index < 0 or slice_index >= len(assigned):
        return None

    candidate = assigned[slice_index]
    if isinstance(candidate, ast.Name):
        return candidate.id
    if isinstance(candidate, ast.Attribute):
        return candidate.attr
    return None


def _extract_constant_index(slice_node: ast.AST) -> int | None:
    if isinstance(slice_node, ast.Constant) and isinstance(slice_node.value, int):
        return slice_node.value
    return None


def _latest_by_line[T](entries: Sequence[tuple[int, T]], line_0: int) -> T | None:
    """Pick highest line_num <= line_0, ties to last-appended (>= comparison); None if none."""
    best: T | None = None
    best_line = -1
    for entry_line, value in entries:
        if entry_line <= line_0 and entry_line >= best_line:
            best = value
            best_line = entry_line
    return best


def _find_latest_name_assignment(index: _CallSiteIndex, name: str, line_0: int) -> ast.expr | None:
    # Max line <= line_0, last-write-wins over walk-ordered Name-target Assigns; returns same node.
    return _latest_by_line(index.name_assignments.get(name, ()), line_0)


def _find_latest_starred_assignment_values(
    index: _CallSiteIndex, starred_name: str, line_0: int
) -> list[ast.expr] | None:
    # Same "max line <= line_0, last-on-tie" as name map, over precomputed distributed-RHS slices.
    return _latest_by_line(index.starred_assignments.get(starred_name, ()), line_0)


def _has_function_definition(index: _CallSiteIndex, name: str, line_0: int) -> bool:
    return any((node.lineno - 1) <= line_0 for node in index.func_defs.get(name, ()))


def _infer_local_function_return_type(
    index: _CallSiteIndex, func_name: str, line_0: int, seen: set[str] | None = None
) -> str:
    # Walk order: def (name match, line <= line_0) with non-Unknown return wins; recurses on Name.
    # seen guards mutual recursion (a returns b, b returns a); it accumulates across the
    # func_defs loop, so two unrelated same-named defs may over-defer to "Unknown" (harmless).
    seen = seen if seen is not None else set()
    if func_name in seen:
        return "Unknown"
    seen.add(func_name)

    result = "Unknown"
    for node in index.func_defs.get(func_name, ()):
        if (node.lineno - 1) > line_0:
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.Return) or stmt.value is None:
                continue
            inferred = _infer_literal_type(stmt.value)
            if inferred != "Unknown":
                result = inferred
                break
            if isinstance(stmt.value, ast.Name):
                nested = _infer_local_function_return_type(index, stmt.value.id, line_0, seen)
                if nested != "Unknown":
                    result = nested
                    break
        if result != "Unknown":
            break

    return result


def _constant_type(const: ast.Constant, *, bytes_as_bytes: bool = False) -> str:
    """Map primitive ``Constant`` to type str; ``bytes_as_bytes`` gives "bytes" not "Unknown"."""
    if const.value is None:
        return "None"
    if isinstance(const.value, bool):
        return "bool"
    if isinstance(const.value, int):
        return "int"
    if isinstance(const.value, float):
        return "float"
    if isinstance(const.value, str):
        return "str"
    if bytes_as_bytes and isinstance(const.value, bytes):
        return "bytes"
    return "Unknown"


def _infer_literal_type(node: ast.AST) -> str:
    if isinstance(node, ast.Constant):
        return _constant_type(node)
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
    scope_map: dict[tuple[str | None, str, int | None], Scope],
    module_scope: Scope,
    script: jedi.Script,
    cancel_token: CancellationToken | None = None,
) -> None:
    """Extract ``self.attr = value`` assigns into method scopes; cancel_token bails mid-walk."""
    # Keyed (parent_name, func_name, def_line): a non-class parent collapses to None, so without
    # the line a nested `def helper` collides with a module-level one.
    method_scopes: dict[tuple[str | None, str, int | None], Scope] = {}
    for scope in scope_tree.scopes_by_id.values():
        if scope.scope_type == ScopeType.FUNCTION and scope.parent:
            parent_name = scope.parent.name if scope.parent.scope_type == ScopeType.CLASS else None
            method_scopes[(parent_name, scope.name, getattr(scope.ast_node, "lineno", None))] = (
                scope
            )

    # Set parent references on AST nodes for proper traversal
    set_parent_refs(tree)

    # Walk the AST to find attribute assignments
    for node in ast.walk(tree):
        if cancel_token is not None and cancel_token.cancelled():
            break
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            # Get the scope for this function
            parent: ast.AST | None = getattr(node, "parent", None)
            parent_name = None
            if parent and isinstance(parent, ast.ClassDef):
                parent_name = parent.name

            scope_key = (parent_name, node.name, node.lineno)
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
    """Process a single attribute assignment and add it to the scope."""
    if not isinstance(target, ast.Attribute):
        return

    # Check if it's an attribute assignment on a name (e.g., self.attr or obj.attr)
    if isinstance(target.value, ast.Name):
        obj_name = target.value.id
        attr_name = target.attr

        # Key self.* by bare attribute name; other objects by qualified name like "point.x".
        key = attr_name if obj_name == "self" else f"{obj_name}.{attr_name}"

        # Infer type from the value, resolving names/calls from scope context when possible.
        type_str = _infer_type_from_ast(value, func_scope, script) if value else "Unknown"

        type_info = TypeInfo(
            type_str=type_str,
            source=TypeSource.LITERAL,
            line=target.lineno - 1 if hasattr(target, "lineno") else 0,
            col=(
                script_byte_col_to_codepoint(script, target.lineno, target.col_offset)
                if hasattr(target, "col_offset")
                else 0
            ),
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
        col=(
            script_byte_col_to_codepoint(script, target.lineno, target.col_offset)
            if hasattr(target, "col_offset")
            else 0
        ),
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
    """Infer a type string from an AST node."""
    if node is None:
        return "Unknown"

    if isinstance(node, ast.Constant):
        return _constant_type(node, bytes_as_bytes=True)

    container = literal_container_annotation(node)
    if container is not None:
        return container

    if isinstance(node, ast.Name):
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
        return _infer_augmented_type(lhs, rhs, node.op)
    elif isinstance(node, ast.Call):
        return _infer_call_return_type(script, node)
    else:
        return "Unknown"
