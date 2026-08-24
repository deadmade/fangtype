"""Adopt base-class signatures for override params/returns, binding subscripted base's typevar."""

from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from fangtype.analysis.types import Scope, ScopeTree, ScopeType, TypeInfo, TypeSource
from fangtype.inference.jedi.positions import script_byte_col_to_codepoint

if TYPE_CHECKING:
    import jedi

logger = logging.getLogger(__name__)

# Conventional typevar names (T, _T, K, V, S, R, U); longer ones are real classes, not substituted.
_TYPEVAR_NAME = re.compile(r"^_?(?:T|K|V|S|R|U)\d?$")

# Typeshed spells typevars as short all-caps names (_T, _KT, _T_co) or AnyStr. None of them are
# defined in the user's file, so an annotation still naming one cannot be inserted.
# ponytail: name-shaped heuristic, so a genuine short all-caps base class (IO, ABC) is dropped
# too -- costs one annotation, never corrupts. Resolve against the file's symbols if that bites.
_LEAKED_TYPEVAR = re.compile(r"^(?:_?[A-Z]{1,3}\d?(?:_co|_contra)?|AnyStr)$")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

_SELF_LIKE = ("self", "cls")


@dataclass
class _BaseSignature:
    """A base-class method signature parsed from a Jedi type hint."""

    params: list[tuple[str, str | None]]
    return_annotation: str | None
    # posonly+regular count; kwonly params live past it and must not match by positional index.
    # None means "treat the whole list as positional" (legacy/hand-built signatures).
    num_positional: int | None = None


def apply_override_inference(script: jedi.Script, scope_tree: ScopeTree) -> None:
    """Fill method param/return types from annotated base-class signatures."""
    signature_cache: dict[str, dict[str, _BaseSignature]] = {}

    for func_scope in scope_tree.get_all_function_scopes():
        class_scope = func_scope.parent
        if class_scope is None or class_scope.scope_type != ScopeType.CLASS:
            continue
        class_node = class_scope.ast_node
        if not isinstance(class_node, ast.ClassDef) or not class_node.bases:
            continue
        func_node = func_scope.ast_node
        if not isinstance(func_node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue

        for base_expr in class_node.bases:
            base_core, type_args = _split_base(base_expr)
            signatures = _base_signatures(script, base_core, signature_cache)
            signature = signatures.get(func_scope.name)
            if signature is None:
                continue
            _apply_signature(func_scope, func_node, signature, type_args)
            break  # first base defining the method wins (approximates MRO)


def _split_base(base_expr: ast.expr) -> tuple[ast.expr, list[str]]:
    """Split ``Visitor[str]`` into the base expression and its type arguments."""
    if not isinstance(base_expr, ast.Subscript):
        return base_expr, []
    slice_node = base_expr.slice
    elements = slice_node.elts if isinstance(slice_node, ast.Tuple) else [slice_node]
    try:
        type_args = [ast.unparse(element) for element in elements]
    except Exception:
        type_args = []
    return base_expr.value, type_args


def _base_signatures(
    script: jedi.Script,
    base_core: ast.expr,
    cache: dict[str, dict[str, _BaseSignature]],
) -> dict[str, _BaseSignature]:
    """Resolve a base-class expression to its method signatures, cached per file."""
    try:
        cache_key = ast.unparse(base_core)
    except Exception:
        return {}
    if cache_key in cache:
        return cache[cache_key]

    signatures: dict[str, _BaseSignature] = {}
    line = getattr(base_core, "end_lineno", None) or getattr(base_core, "lineno", None)
    col = getattr(base_core, "end_col_offset", 1)
    if line is not None:
        col_cp = script_byte_col_to_codepoint(script, line, col)
        try:
            values = script.infer(line, max(col_cp - 1, 0))
        except Exception as e:
            logger.debug("Base class inference failed for %s: %s", cache_key, e)
            values = []
        for value in values:
            if getattr(value, "type", None) != "class":
                continue
            signatures.update(_class_member_signatures(value))
    cache[cache_key] = signatures
    return signatures


def _class_member_signatures(class_value: Any) -> dict[str, _BaseSignature]:
    signatures: dict[str, _BaseSignature] = {}
    try:
        members = class_value.defined_names()
    except Exception as e:
        logger.debug("defined_names failed for %s: %s", class_value, e)
        return signatures
    for member in members:
        if getattr(member, "type", None) != "function":
            continue
        try:
            hint = member.get_type_hint()
        except Exception:
            continue
        if not hint:
            continue
        signature = _parse_signature(hint)
        if signature is not None:
            signatures[str(member.name)] = signature
    return signatures


def _parse_signature(hint: str) -> _BaseSignature | None:
    """Parse a Jedi function hint like ``visit(self, t: Instance) -> T``."""
    text = hint.strip()
    if text.startswith("def "):
        text = text[len("def ") :]
    try:
        module = ast.parse(f"def {text}:\n    pass")
    except SyntaxError:
        return None
    func = module.body[0]
    if not isinstance(func, ast.FunctionDef):
        return None
    positional_args = [*func.args.posonlyargs, *func.args.args]
    params: list[tuple[str, str | None]] = []
    for arg in [*positional_args, *func.args.kwonlyargs]:
        annotation = ast.unparse(arg.annotation) if arg.annotation is not None else None
        params.append((arg.arg, annotation))
    return_annotation = ast.unparse(func.returns) if func.returns is not None else None
    return _BaseSignature(
        params=params,
        return_annotation=return_annotation,
        num_positional=len(positional_args),
    )


def _substitute_typevar(annotation: str, type_args: list[str]) -> tuple[str, bool]:
    """Substitute a bare conventional typevar bound by a single-arg generic base."""
    if len(type_args) == 1 and _TYPEVAR_NAME.match(annotation):
        return type_args[0], True
    return annotation, False


def _leaks_typevar(annotation: str) -> bool:
    """Whether an annotation still names a base typevar, undefined in the user's file."""
    return any(_LEAKED_TYPEVAR.match(token) for token in _IDENTIFIER.findall(annotation))


def _positional_params(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.arg]:
    return [*func_node.args.posonlyargs, *func_node.args.args]


def _base_positional(signature: _BaseSignature) -> list[tuple[str, str | None]]:
    """Base positional params aligned to include a leading self slot (kwonly excluded)."""
    params = signature.params
    if signature.num_positional is not None:
        params = params[: signature.num_positional]
    if params and params[0][0] in _SELF_LIKE:
        return params
    # Jedi hints for bound methods omit self; re-align by prepending a slot.
    return [("self", None), *params]


def _lookup_base_annotation(
    signature: _BaseSignature, param_name: str, position: int | None
) -> str | None:
    for name, annotation in signature.params:
        if name == param_name and name not in _SELF_LIKE:
            return annotation
    base_positional = _base_positional(signature)
    if position is not None and 0 < position < len(base_positional):
        return base_positional[position][1]
    return None


def _none_default_names(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    names: set[str] = set()
    positional = _positional_params(func_node)
    defaults = func_node.args.defaults
    defaulted = positional[len(positional) - len(defaults) :]
    for arg, default in zip(defaulted, defaults, strict=False):
        if isinstance(default, ast.Constant) and default.value is None:
            names.add(arg.arg)
    for arg, kw_default in zip(func_node.args.kwonlyargs, func_node.args.kw_defaults, strict=False):
        if isinstance(kw_default, ast.Constant) and kw_default.value is None:
            names.add(arg.arg)
    return names


def annotation_includes_none(annotation: str) -> bool:
    """Whether a rendered annotation already admits ``None``."""
    if annotation.startswith("Optional["):
        return True
    return "None" in [member.strip() for member in annotation.split("|")]


def _is_bare_callable(type_str: str) -> bool:
    """Whether a return type is a bare ``Callable`` -- jedi's lossy collapse of a returned func."""
    non_none = [member.strip() for member in type_str.split("|") if member.strip() != "None"]
    return non_none == ["Callable"]


def _is_parameterized_callable(annotation: str) -> bool:
    """Whether an annotation actually carries a ``Callable[...]`` signature."""
    return "Callable[" in annotation


def _apply_signature(
    func_scope: Scope,
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
    signature: _BaseSignature,
    type_args: list[str],
) -> None:
    none_defaults = _none_default_names(func_node)

    own_positional = _positional_params(func_node)
    targets: list[tuple[ast.arg, int | None]] = [
        (arg, position) for position, arg in enumerate(own_positional)
    ]
    targets += [(arg, None) for arg in func_node.args.kwonlyargs]
    for arg, position in targets:
        if position == 0 and arg.arg in _SELF_LIKE:
            continue
        annotation = _lookup_base_annotation(signature, arg.arg, position)
        if annotation is None:
            continue
        annotation, _ = _substitute_typevar(annotation, type_args)
        if _leaks_typevar(annotation):
            continue
        if arg.arg in none_defaults and not annotation_includes_none(annotation):
            annotation = f"{annotation} | None"
        func_scope.add_parameter(
            arg.arg,
            TypeInfo(
                type_str=annotation,
                source=TypeSource.INHERITED,
                line=arg.lineno - 1,
                col=arg.col_offset,
            ),
        )

    if signature.return_annotation is not None:
        return_annotation, substituted = _substitute_typevar(signature.return_annotation, type_args)
        if _leaks_typevar(return_annotation):
            return
        current = func_scope.return_type
        # Substituted typevar wins; base return only fills gaps; parameterized Callable beats bare.
        replaces_bare_callable = (
            current is not None
            and _is_bare_callable(current.type_str)
            and _is_parameterized_callable(return_annotation)
        )
        if (
            substituted
            or current is None
            or current.type_str in ("", "Unknown")
            or replaces_bare_callable
        ):
            func_scope.return_type = TypeInfo(
                type_str=return_annotation,
                source=TypeSource.INHERITED,
                line=func_node.lineno - 1,
                col=func_node.col_offset,
            )
