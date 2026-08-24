"""Backend type-lookup seam (TypeProbe) for call-flow inference; JediProbe implements it."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import ast


@runtime_checkable
class TypeProbe(Protocol):
    """Backend-specific type lookup — the only thing the shared pipeline needs."""

    def infer_expr_type(self, expr: ast.expr) -> str:
        """Return a normalized type string for an AST expression, or "Unknown"."""
        ...
