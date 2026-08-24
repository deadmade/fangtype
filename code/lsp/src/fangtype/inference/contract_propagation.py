"""Fill dead-end callback params from a base method's Callable contract (params-only, fill-only)."""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fangtype.analysis.types import Scope, ScopeTree, ScopeType, TypeInfo, TypeSource
from fangtype.inference import override_inference as oi

if TYPE_CHECKING:
    import jedi

    from fangtype.cancellation import CancellationToken


logger = logging.getLogger(__name__)


# Pure analysis logic (no Jedi, no filesystem) -- unit-tested.


@dataclass(frozen=True)
class CallableContract:
    """Resolved Callable contract: ordered param type strings (None for ...) and return type."""

    params: list[str] | None
    ret: str

    def _key(self) -> tuple[tuple[str, ...] | None, str]:
        return (tuple(self.params) if self.params is not None else None, self.ret)


def _split_top_level_union(annotation: str) -> list[str]:
    """Split on top-level ``|`` only, respecting ``[]`` and ``()`` nesting."""
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for ch in annotation:
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
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return [p for p in parts if p]


def parse_callable_contract(annotation: str | None) -> CallableContract | None:
    """Parse a ``Callable[[...], Y]`` contract (strip ``| None``); ``...`` yields params=None."""
    if not annotation:
        return None

    non_none = [p for p in _split_top_level_union(annotation) if p != "None"]
    if len(non_none) != 1:
        return None
    member = non_none[0]

    try:
        node = ast.parse(member, mode="eval").body
    except SyntaxError:
        return None
    if not isinstance(node, ast.Subscript):
        return None

    # Accept ``Callable``, ``typing.Callable``, ``collections.abc.Callable``.
    base = node.value
    base_name = (
        base.id
        if isinstance(base, ast.Name)
        else (base.attr if isinstance(base, ast.Attribute) else None)
    )
    if base_name != "Callable":
        return None

    slice_node = node.slice
    if not isinstance(slice_node, ast.Tuple) or len(slice_node.elts) != 2:
        return None
    params_node, return_node = slice_node.elts

    if isinstance(params_node, ast.List):
        params: list[str] | None = [ast.unparse(elt) for elt in params_node.elts]
    elif isinstance(params_node, ast.Constant) and params_node.value is Ellipsis:
        params = None
    else:
        return None

    return CallableContract(params=params, ret=ast.unparse(return_node))


def _own_return_nodes(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.Return]:
    """This function's own ``ast.Return`` nodes, stopping at any nested def/lambda boundary."""
    returns: list[ast.Return] = []

    def visit(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
                continue
            if isinstance(child, ast.Return):
                returns.append(child)
            visit(child)

    visit(func_node)
    return returns


def _plain_name_return_nodes(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[ast.Name]:
    """First ``ast.Name`` per bare ``return N`` in the function's own body (for a Jedi goto)."""
    nodes: list[ast.Name] = []
    seen: set[str] = set()
    for node in _own_return_nodes(func_node):
        if isinstance(node.value, ast.Name) and node.value.id not in seen:
            seen.add(node.value.id)
            nodes.append(node.value)
    return nodes


def align_contract(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
    contract: CallableContract,
) -> dict[str, str]:
    """Map a contract onto a callback's slots, fill-only (skip self/cls and annotated params)."""
    proposals: dict[str, str] = {}

    positional = oi._positional_params(func_node)
    if positional and positional[0].arg in oi._SELF_LIKE:
        positional = positional[1:]

    if contract.params is not None:
        for arg, ptype in zip(positional, contract.params, strict=False):
            if arg.annotation is None:
                proposals[arg.arg] = ptype

    if func_node.returns is None:
        proposals["return"] = contract.ret

    return proposals


def merge_contracts(contracts: list[CallableContract]) -> tuple[CallableContract | None, str]:
    """Apply the conflict rule: all-agree -> ok, disagree -> conflict, none -> no_contract."""
    if not contracts:
        return None, "no_contract"
    unique: dict[tuple[tuple[str, ...] | None, str], CallableContract] = {}
    for contract in contracts:
        unique[contract._key()] = contract
    if len(unique) == 1:
        return next(iter(unique.values())), "ok"
    return None, "conflict"


# Jedi-backed logic for params-only contract propagation.


def _bind_contract(contract: CallableContract, type_args: list[str]) -> CallableContract | None:
    """Substitute a single-arg base's typevar into a contract; drop it if a typevar still leaks."""
    ret, _ = oi._substitute_typevar(contract.ret, type_args)
    if oi._leaks_typevar(ret):
        return None
    params = contract.params
    if params is not None:
        bound: list[str] = []
        for param in params:
            substituted, _ = oi._substitute_typevar(param, type_args)
            if oi._leaks_typevar(substituted):
                return None
            bound.append(substituted)
        params = bound
    return CallableContract(params=params, ret=ret)


def _hook_contracts_for_class(
    script: jedi.Script,
    class_node: ast.ClassDef,
    sig_cache: dict[str, dict[str, oi._BaseSignature]],
) -> dict[str, CallableContract]:
    """Map method-name -> Callable contract from this class's overridden base-method returns."""
    contracts: dict[str, CallableContract] = {}
    for base_expr in class_node.bases:
        base_core, type_args = oi._split_base(base_expr)
        signatures = oi._base_signatures(script, base_core, sig_cache)
        for method_name, signature in signatures.items():
            if method_name in contracts:
                continue
            contract = parse_callable_contract(signature.return_annotation)
            if contract is None:
                continue
            bound = _bind_contract(contract, type_args)
            if bound is not None:
                contracts[method_name] = bound
    return contracts


# Production pass: params-only, fill-only, wired into the Jedi scope builder.


def _same_file(script: jedi.Script, definition: Any) -> bool:
    """Whether a Jedi definition resolves into the same file as ``script`` (same-file stage)."""
    script_path = getattr(script, "path", None)
    module_path = getattr(definition, "module_path", None)
    if script_path is None or module_path is None:
        return script_path is None and module_path is None
    try:
        return Path(module_path).resolve() == Path(script_path).resolve()
    except Exception:
        return False


def _resolve_return_target_scope(
    script: jedi.Script,
    name_node: ast.Name,
    scope_tree: ScopeTree,
) -> Scope | None:
    """Resolve a ``return <Name>`` to the function scope it names, same file only."""
    try:
        definitions = script.goto(
            name_node.lineno,
            name_node.col_offset,
            follow_imports=True,
            follow_builtin_imports=False,
        )
    except Exception as e:
        logger.debug("goto failed for returned name %r: %s", name_node.id, e)
        return None

    for definition in definitions:
        if getattr(definition, "type", None) != "function":
            continue
        if not _same_file(script, definition):
            continue
        line = getattr(definition, "line", None)
        if line is None:
            continue
        candidate = scope_tree.find_scope_for_line(line - 1)
        if (
            candidate.scope_type == ScopeType.FUNCTION
            and candidate.name == definition.name
            and isinstance(candidate.ast_node, ast.FunctionDef | ast.AsyncFunctionDef)
            and candidate.ast_node.lineno == line
        ):
            return candidate
    return None


def _param_has_inferred_type(func_scope: Scope, param_name: str) -> bool:
    current = func_scope.parameters.get(param_name)
    return current is not None and current.type_str not in ("", "Unknown")


def _find_arg_node(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef, param_name: str
) -> ast.arg | None:
    for arg in oi._positional_params(func_node):
        if arg.arg == param_name:
            return arg
    return None


def _apply_param_fill(func_scope: Scope, param_name: str, annotation: str) -> None:
    """Fill a parameter slot, but never overwrite an already-inferred type."""
    if _param_has_inferred_type(func_scope, param_name):
        return
    func_node = func_scope.ast_node
    if not isinstance(func_node, ast.FunctionDef | ast.AsyncFunctionDef):
        return
    arg_node = _find_arg_node(func_node, param_name)
    line = arg_node.lineno - 1 if arg_node is not None else func_node.lineno - 1
    col = arg_node.col_offset if arg_node is not None else func_node.col_offset
    func_scope.add_parameter(
        param_name,
        TypeInfo(type_str=annotation, source=TypeSource.INHERITED, line=line, col=col),
    )


# Cross-file discovery: dead-end candidates + project-wide reference evidence.


@dataclass
class _ExternalFile:
    """Parsed state for another project file consulted as cross-file evidence."""

    script: jedi.Script
    # (line, col, name) of a plain-name return -> its (class node, method name).
    return_sites: dict[tuple[int, int, str], tuple[ast.ClassDef, str]]
    sig_cache: dict[str, dict[str, oi._BaseSignature]]
    # Hook contracts per class, keyed by the class node's line (resolved lazily).
    hooks_by_class: dict[int, dict[str, CallableContract]]


def _dead_end_module_functions(scope_tree: ScopeTree) -> list[Scope]:
    """Module-level function scopes whose positional params are ALL still untyped."""
    candidates: list[Scope] = []
    for scope in scope_tree.get_all_function_scopes():
        parent = scope.parent
        if parent is None or parent.scope_type != ScopeType.MODULE:
            continue
        func_node = scope.ast_node
        if not isinstance(func_node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        positional = oi._positional_params(func_node)
        if not positional:
            continue
        if any(arg.annotation is not None for arg in positional):
            continue
        if any(_param_has_inferred_type(scope, arg.arg) for arg in positional):
            continue
        candidates.append(scope)
    return candidates


def _load_external_file(
    path: Path,
    project: Any,
    cache: dict[Path, _ExternalFile | None],
) -> _ExternalFile | None:
    """Parse + index another project file (cached per propagation run)."""
    if path in cache:
        return cache[path]
    import jedi

    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        ext_script = jedi.Script(code=source, path=str(path), project=project)
    except Exception as e:
        logger.debug("Skipping external file %s: %s", path, e)
        cache[path] = None
        return None

    return_sites: dict[tuple[int, int, str], tuple[ast.ClassDef, str]] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.bases):
            continue
        for member in node.body:
            if not isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for stmt in _own_return_nodes(member):
                if isinstance(stmt.value, ast.Name):
                    key = (stmt.value.lineno, stmt.value.col_offset, stmt.value.id)
                    return_sites[key] = (node, member.name)

    entry = _ExternalFile(
        script=ext_script, return_sites=return_sites, sig_cache={}, hooks_by_class={}
    )
    cache[path] = entry
    return entry


def _external_contract_at(
    ext: _ExternalFile, line: int, col: int, name: str
) -> CallableContract | None:
    """Contract flowing through a ``return <name>`` site in an external file."""
    site = ext.return_sites.get((line, col, name))
    if site is None:
        return None
    class_node, method_name = site
    hooks = ext.hooks_by_class.get(class_node.lineno)
    if hooks is None:
        hooks = _hook_contracts_for_class(ext.script, class_node, ext.sig_cache)
        ext.hooks_by_class[class_node.lineno] = hooks
    return hooks.get(method_name)


def _module_function_names(script: jedi.Script) -> dict[tuple[str, int], Any]:
    """Jedi definition names for the analyzed module's top-level functions."""
    try:
        names = script.get_names(all_scopes=False, definitions=True, references=False)
    except Exception as e:
        logger.debug("get_names failed for cross-file discovery: %s", e)
        return {}
    return {
        (str(name.name), name.line): name
        for name in names
        if getattr(name, "type", None) == "function" and name.line is not None
    }


def _cross_file_contracts(
    script: jedi.Script,
    candidates: list[Scope],
    cancel_token: CancellationToken | None = None,
) -> dict[str, list[CallableContract]]:
    """Collect dead-end candidates' hook contracts from other files' plain-name returns."""
    contracts: dict[str, list[CallableContract]] = {}
    def_names = _module_function_names(script)
    if not def_names:
        return contracts

    script_path = Path(script.path).resolve() if script.path is not None else None
    # jedi.Script has no public project accessor; auto-detect if the private attr moves.
    project = getattr(getattr(script, "_inference_state", None), "project", None)
    file_cache: dict[Path, _ExternalFile | None] = {}

    for scope in candidates:
        if cancel_token is not None and cancel_token.cancelled():
            break
        func_node = scope.ast_node
        if not isinstance(func_node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        def_name = def_names.get((scope.name, func_node.lineno))
        if def_name is None:
            continue
        try:
            references = script.get_references(
                def_name.line, def_name.column, include_builtins=False
            )
        except Exception as e:
            logger.debug("get_references failed for %r: %s", scope.name, e)
            continue

        for reference in references:
            if cancel_token is not None and cancel_token.cancelled():
                break
            module_path = getattr(reference, "module_path", None)
            line = getattr(reference, "line", None)
            column = getattr(reference, "column", None)
            if module_path is None or line is None or column is None:
                continue
            ref_path = Path(module_path).resolve()
            if script_path is not None and ref_path == script_path:
                continue  # same-file evidence is stage one's job
            ext = _load_external_file(ref_path, project, file_cache)
            if ext is None:
                continue
            contract = _external_contract_at(ext, line, column, scope.name)
            if contract is not None:
                contracts.setdefault(scope.scope_id, []).append(contract)

    return contracts


def _apply_contracts(
    scope_tree: ScopeTree,
    contracts_by_target: dict[str, list[CallableContract]],
) -> None:
    """Merge each target's contracts (conflict -> skip) and fill its slots."""
    for scope_id, contracts in contracts_by_target.items():
        merged, _reason = merge_contracts(contracts)
        if merged is None:
            continue
        target_scope = scope_tree.scopes_by_id.get(scope_id)
        if target_scope is None:
            continue
        func_node = target_scope.ast_node
        if not isinstance(func_node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue

        for slot, annotation in align_contract(func_node, merged).items():
            if slot == "return":
                continue
            _apply_param_fill(target_scope, slot, annotation)


def apply_contract_propagation(
    script: jedi.Script,
    scope_tree: ScopeTree,
    *,
    enable_cross_file: bool = True,
    cancel_token: CancellationToken | None = None,
) -> None:
    """Fill dead-end callback params from a hook's Callable contract; same-file then cross-file."""
    signature_cache: dict[str, dict[str, oi._BaseSignature]] = {}
    contracts_by_target: dict[str, list[CallableContract]] = {}

    for func_scope in scope_tree.get_all_function_scopes():
        if cancel_token is not None and cancel_token.cancelled():
            break
        class_scope = func_scope.parent
        if class_scope is None or class_scope.scope_type != ScopeType.CLASS:
            continue
        class_node = class_scope.ast_node
        if not isinstance(class_node, ast.ClassDef) or not class_node.bases:
            continue
        func_node = func_scope.ast_node
        if not isinstance(func_node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue

        hook_contracts = _hook_contracts_for_class(script, class_node, signature_cache)
        contract = hook_contracts.get(func_scope.name)
        if contract is None:
            continue

        for name_node in _plain_name_return_nodes(func_node):
            target_scope = _resolve_return_target_scope(script, name_node, scope_tree)
            if target_scope is None:
                continue
            contracts_by_target.setdefault(target_scope.scope_id, []).append(contract)

    _apply_contracts(scope_tree, contracts_by_target)

    # Stage two: cross-file evidence for dead-end candidates; same-file contracts stay in the merge.
    candidates = _dead_end_module_functions(scope_tree)
    if not candidates:
        return
    cross_contracts: dict[str, list[CallableContract]] = {}
    if enable_cross_file:
        cross_contracts = _cross_file_contracts(script, candidates, cancel_token)
    if not cross_contracts:
        return
    for scope_id, found in cross_contracts.items():
        merged_evidence = contracts_by_target.get(scope_id, []) + found
        cross_contracts[scope_id] = merged_evidence
    _apply_contracts(scope_tree, cross_contracts)
