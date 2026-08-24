"""Memoizing TypeProbe decorator: caches by expr position; source immutable per infer_types call."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import ast

    from fangtype.protocols.type_probe_protocol import TypeProbe


class CachingProbe:
    """Memoizing decorator — the source is immutable within one infer_types call."""

    def __init__(self, inner: TypeProbe) -> None:
        self._inner = inner
        self._cache: dict[tuple[int | None, int | None, int | None, int | None], str] = {}

    def infer_expr_type(self, expr: ast.expr) -> str:
        key = (expr.lineno, expr.col_offset, expr.end_lineno, expr.end_col_offset)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        result = self._inner.infer_expr_type(expr)
        self._cache[key] = result
        return result
