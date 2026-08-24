"""Scope.get_variable_type_at_line must read the newest binding by LINE, not by append order."""

from __future__ import annotations

import ast

from fangtype.analysis import Scope, ScopeType, TypeInfo, TypeSource


def _scope() -> Scope:
    return Scope(
        scope_id="m",
        scope_type=ScopeType.MODULE,
        name="module",
        ast_node=ast.parse(""),
    )


def test_out_of_order_append_does_not_return_a_stale_earlier_line() -> None:
    """A later pass re-recording line 1 must not shadow the line 2 binding (was: 'Widget')."""
    scope = _scope()
    scope.add_variable("x", TypeInfo("Unknown", TypeSource.UNKNOWN, line=1, col=4))
    scope.add_variable("x", TypeInfo("int", TypeSource.LITERAL, line=2, col=4))
    # Pass 4 resolves line 1 afterwards and appends it out of line order.
    scope.add_variable("x", TypeInfo("Widget", TypeSource.FUNCTION_CALL, line=1, col=4))

    info = scope.get_variable_type_at_line("x", 3)

    assert info is not None
    assert info.type_str == "int"


def test_same_line_refinement_wins_over_earlier_guess() -> None:
    """Among bindings sharing the newest line, the last-appended (refined) one is returned."""
    scope = _scope()
    scope.add_variable("y", TypeInfo("Unknown", TypeSource.UNKNOWN, line=1, col=4))
    scope.add_variable("y", TypeInfo("Widget", TypeSource.FUNCTION_CALL, line=1, col=4))

    info = scope.get_variable_type_at_line("y", 2)

    assert info is not None
    assert info.type_str == "Widget"
