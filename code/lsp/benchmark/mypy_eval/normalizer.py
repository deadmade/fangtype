"""Normalization helpers for semantic annotation comparison."""

import ast

_BUILTIN_ALIAS_MAP = {
    "Dict": "dict",
    "FrozenSet": "frozenset",
    "List": "list",
    "Set": "set",
    "Text": "str",
    "Tuple": "tuple",
    "Type": "type",
}


def _strip_module_qualifiers(node: ast.expr) -> ast.expr:
    """Collapse dotted ``module.….Name`` chains to their final bare ``Name``."""
    if isinstance(node, ast.Attribute):
        root = node.value
        while isinstance(root, ast.Attribute):
            root = root.value
        if isinstance(root, ast.Name):
            return ast.copy_location(ast.Name(id=node.attr, ctx=ast.Load()), node)
        return ast.copy_location(
            ast.Attribute(value=_strip_module_qualifiers(node.value), attr=node.attr, ctx=node.ctx),
            node,
        )

    if isinstance(node, ast.Subscript):
        return ast.copy_location(
            ast.Subscript(
                value=_strip_module_qualifiers(node.value),
                slice=_strip_module_qualifiers(node.slice),
                ctx=node.ctx,
            ),
            node,
        )

    if isinstance(node, ast.Tuple):
        return ast.copy_location(
            ast.Tuple(elts=[_strip_module_qualifiers(elt) for elt in node.elts], ctx=node.ctx),
            node,
        )

    if isinstance(node, ast.List):
        return ast.copy_location(
            ast.List(elts=[_strip_module_qualifiers(elt) for elt in node.elts], ctx=node.ctx),
            node,
        )

    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return ast.copy_location(
            ast.BinOp(
                left=_strip_module_qualifiers(node.left),
                op=node.op,
                right=_strip_module_qualifiers(node.right),
            ),
            node,
        )

    return node


def _typing_alias_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return _BUILTIN_ALIAS_MAP.get(node.id)
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "typing"
    ):
        return _BUILTIN_ALIAS_MAP.get(node.attr)
    return None


def _union_members(node: ast.expr) -> list[ast.expr] | None:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left = _union_members(node.left) or [node.left]
        right = _union_members(node.right) or [node.right]
        return left + right

    alias = _typing_alias_name(node)
    if alias == "None":
        return [node]

    if isinstance(node, ast.Subscript):
        union_alias = _typing_alias_name(node.value)
        if union_alias is None and not (
            isinstance(node.value, ast.Name) and node.value.id in {"Optional", "Union"}
        ):
            return None

        if isinstance(node.value, ast.Name) and node.value.id == "Optional":
            return [_normalize_expr(node.slice), ast.Constant(value=None)]

        if isinstance(node.value, ast.Name) and node.value.id == "Union":
            if isinstance(node.slice, ast.Tuple):
                return [_normalize_expr(elt) for elt in node.slice.elts]
            return [_normalize_expr(node.slice)]

    return None


def _fold_union(members: list[ast.expr], node: ast.expr) -> ast.expr:
    """Normalize, sort, and de-duplicate union members into a canonical BinOp chain."""
    seen: set[str] = set()
    deduped: list[ast.expr] = []
    for member in sorted(
        (_normalize_expr(member) for member in members),
        key=ast.unparse,
    ):
        key = ast.unparse(member)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(member)

    current = deduped[0]
    for member in deduped[1:]:
        current = ast.BinOp(left=current, op=ast.BitOr(), right=member)
    return ast.copy_location(current, node)


def _normalize_expr(node: ast.expr) -> ast.expr:
    alias = _typing_alias_name(node)
    if alias is not None:
        return ast.copy_location(ast.Name(id=alias, ctx=ast.Load()), node)

    # ``NoneType`` (what Jedi infers) denotes the same type as the ``None`` literal
    # written in source annotations.
    if isinstance(node, ast.Name) and node.id == "NoneType":
        return ast.copy_location(ast.Constant(value=None), node)

    if isinstance(node, ast.Subscript):
        optional_union_members = _union_members(node)
        if optional_union_members is not None:
            return _fold_union(optional_union_members, node)

        return ast.copy_location(
            ast.Subscript(
                value=_normalize_expr(node.value),
                slice=_normalize_expr(node.slice),
                ctx=node.ctx,
            ),
            node,
        )

    if isinstance(node, ast.Tuple):
        return ast.copy_location(
            ast.Tuple(elts=[_normalize_expr(elt) for elt in node.elts], ctx=node.ctx),
            node,
        )

    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        members = _union_members(node) or [node.left, node.right]
        return _fold_union(members, node)

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            parsed = ast.parse(node.value, mode="eval")
        except SyntaxError:
            return ast.copy_location(ast.Constant(value=" ".join(node.value.split())), node)
        return ast.copy_location(_normalize_expr(_strip_module_qualifiers(parsed.body)), node)

    return node


def normalize_annotation(annotation: str) -> str:
    """Normalize an annotation string for semantic comparison."""
    compact = " ".join(annotation.split())
    try:
        parsed = ast.parse(compact, mode="eval")
    except SyntaxError:
        return compact

    normalized = _normalize_expr(_strip_module_qualifiers(parsed.body))
    return ast.unparse(normalized)


def base_head(normalized: str) -> str | None:
    """Outermost generic base of a normalized annotation.

    ``Callable[[X], Y]`` -> ``Callable``; ``list[int]`` -> ``list``; ``list`` -> ``list``.
    Returns ``None`` when the outermost node is not a Name or a Name-headed Subscript
    (e.g. unions ``int | None``, tuples). Expects an already-normalized string, so it
    composes with :func:`normalize_annotation` rather than re-canonicalizing.
    """
    try:
        node: ast.expr = ast.parse(normalized, mode="eval").body
    except SyntaxError:
        return None
    while isinstance(node, ast.Subscript):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None
