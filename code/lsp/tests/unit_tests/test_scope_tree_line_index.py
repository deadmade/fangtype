"""WP1 O(1) find_scope_for_line matches the old linear scan: verbatim-copy oracle + fuzz cases."""

from __future__ import annotations

import ast
import textwrap
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from fangtype.analysis import Scope, ScopeTree, ScopeType

if TYPE_CHECKING:
    from fangtype.inference.jedi.engine import JediInferenceEngine


def _linear_find_scope_for_line(tree: ScopeTree, line: int) -> Scope:
    """Verbatim pre-WP1 O(S) linear scan (oracle); keep byte-for-byte, do not clean up."""
    best_scope = tree.root

    for scope in tree.scopes_by_id.values():
        if scope.scope_type == ScopeType.MODULE:
            continue

        ast_node = scope.ast_node
        line_range = tree._node_line_range(ast_node)
        if line_range is None:
            continue
        start_line, end_line = line_range

        if start_line <= line <= end_line:
            best_range = tree._node_line_range(best_scope.ast_node)
            best_start = best_range[0] if best_range is not None else -1
            if best_scope.scope_type == ScopeType.MODULE or start_line >= best_start:
                best_scope = scope

    return best_scope


# Oracle cross-check (property test) over real ScopeTrees.

_NESTED_FUNCTIONS = textwrap.dedent(
    """
    def outer(a):
        def inner(b):
            return b + 1

        return inner(a)
    """
).strip()

_CLASS_WITH_METHODS = textwrap.dedent(
    """
    class Foo:
        def method_a(self):
            return 1

        def method_b(self):
            if True:
                return 2
            return 3


    class Bar(Foo):
        def method_a(self):
            return super().method_a()
    """
).strip()

_LAMBDAS = textwrap.dedent(
    """
    f = lambda x: x + 1
    g = lambda y: (
        y * 2
    )

    def uses_lambda(h):
        return h(1)
    """
).strip()

_MODULE_WITH_NONE = textwrap.dedent(
    """
    x = 1
    y = 2
    z = x + y
    """
).strip()

_MIXED_EVERYTHING = textwrap.dedent(
    """
    class Outer:
        class Inner:
            def method(self):
                helper = lambda v: v * 2
                return helper(1)

        def top_method(self, n):
            def local(m):
                return m + n

            return local(n)


    def module_func(a, b):
        return a + b
    """
).strip()


@pytest.mark.parametrize(
    "source",
    [_NESTED_FUNCTIONS, _CLASS_WITH_METHODS, _LAMBDAS, _MODULE_WITH_NONE, _MIXED_EVERYTHING],
    ids=["nested_functions", "class_with_methods", "lambdas", "module_with_none", "mixed"],
)
def test_oracle_cross_check_every_line(engine: JediInferenceEngine, source: str) -> None:
    """New O(1) lookup must agree with the linear-scan oracle for every line queried."""
    result = engine.infer_types(source)
    tree = result.scope_tree

    total_lines = len(source.splitlines())
    for line in range(-2, total_lines + 3):
        fast = tree.find_scope_for_line(line)
        oracle = _linear_find_scope_for_line(tree, line)
        assert fast.scope_id == oracle.scope_id, (
            f"line={line}: fast={fast.scope_id!r} oracle={oracle.scope_id!r}"
        )


def test_oracle_cross_check_repeated_queries_stay_consistent(engine: JediInferenceEngine) -> None:
    """Querying the same tree repeatedly must not build a stale/duplicate index."""
    result = engine.infer_types(_MIXED_EVERYTHING)
    tree = result.scope_tree

    total_lines = len(_MIXED_EVERYTHING.splitlines())
    first_pass = [tree.find_scope_for_line(line).scope_id for line in range(total_lines + 2)]
    second_pass = [tree.find_scope_for_line(line).scope_id for line in range(total_lines + 2)]
    assert first_pass == second_pass


# Hand-built fuzz/edge unit tests (no Jedi) pinning the exact tiebreak.


def _node(lineno: int, end_lineno: int | None) -> ast.AST:
    """Stand-in AST node with only ``lineno``/``end_lineno``, for ``_node_line_range``'s check."""
    return cast("ast.AST", SimpleNamespace(lineno=lineno, end_lineno=end_lineno))


def _make_root() -> Scope:
    """MODULE root with no line-range, like ``ast.Module`` (``_node_line_range`` -> None)."""
    return Scope(
        scope_id="module", scope_type=ScopeType.MODULE, name="module", ast_node=ast.parse("")
    )


def _make_scope(
    scope_id: str,
    start_line: int,
    end_line: int | None,
    scope_type: ScopeType = ScopeType.FUNCTION,
    parent: Scope | None = None,
) -> Scope:
    """Scope from 0-based ``start_line``/``end_line`` (to 1-based); ``None`` end -> start_line."""
    end_lineno = None if end_line is None else end_line + 1
    return Scope(
        scope_id=scope_id,
        scope_type=scope_type,
        name=scope_id,
        ast_node=_node(start_line + 1, end_lineno),
        parent=parent,
    )


def test_nested_scope_with_larger_start_wins() -> None:
    """Inner scope (larger start_line) beats its enclosing outer scope."""
    root = _make_root()
    tree = ScopeTree(root=root)
    tree.add_scope(root)

    outer = _make_scope("outer", start_line=0, end_line=9)
    tree.add_scope(outer)
    inner = _make_scope("inner", start_line=3, end_line=6, parent=outer)
    tree.add_scope(inner)

    # Inside inner's range: inner wins (larger start_line).
    assert tree.find_scope_for_line(3).scope_id == "inner"
    assert tree.find_scope_for_line(4).scope_id == "inner"
    assert tree.find_scope_for_line(6).scope_id == "inner"

    # Inside outer only (before/after inner): outer wins.
    assert tree.find_scope_for_line(0).scope_id == "outer"
    assert tree.find_scope_for_line(2).scope_id == "outer"
    assert tree.find_scope_for_line(7).scope_id == "outer"
    assert tree.find_scope_for_line(9).scope_id == "outer"


def test_zero_width_scope() -> None:
    """A scope whose end == start (single-line node) matches only that one line."""
    root = _make_root()
    tree = ScopeTree(root=root)
    tree.add_scope(root)

    zero_width = _make_scope("zero_width", start_line=5, end_line=5)
    tree.add_scope(zero_width)

    assert tree.find_scope_for_line(5).scope_id == "zero_width"
    assert tree.find_scope_for_line(4).scope_id == "module"
    assert tree.find_scope_for_line(6).scope_id == "module"


def test_end_lineno_none_defaults_to_start_line() -> None:
    """A scope whose ast_node.end_lineno is None: range defaults to (start, start)."""
    root = _make_root()
    tree = ScopeTree(root=root)
    tree.add_scope(root)

    scope = _make_scope("no_end", start_line=7, end_line=None)
    tree.add_scope(scope)

    assert scope.ast_node.end_lineno is None
    assert tree.find_scope_for_line(7).scope_id == "no_end"
    assert tree.find_scope_for_line(8).scope_id == "module"
    assert tree.find_scope_for_line(6).scope_id == "module"


def test_line_before_after_and_module_only() -> None:
    """Lines outside every non-module scope's range fall back to root."""
    root = _make_root()
    tree = ScopeTree(root=root)
    tree.add_scope(root)

    scope = _make_scope("func", start_line=3, end_line=6)
    tree.add_scope(scope)

    assert tree.find_scope_for_line(-1).scope_id == "module"  # before all scopes
    assert tree.find_scope_for_line(0).scope_id == "module"  # module-only region
    assert tree.find_scope_for_line(2).scope_id == "module"  # module-only region
    assert tree.find_scope_for_line(4).scope_id == "func"  # inside the scope
    assert tree.find_scope_for_line(100).scope_id == "module"  # after all scopes


def test_overlapping_siblings_larger_start_wins_regardless_of_order() -> None:
    """Two non-nested (sibling) scopes with overlapping ranges: max-start wins the overlap."""
    root = _make_root()
    tree = ScopeTree(root=root)
    tree.add_scope(root)

    scope_a = _make_scope("a", start_line=0, end_line=10)
    scope_b = _make_scope("b", start_line=5, end_line=15)
    tree.add_scope(scope_a)
    tree.add_scope(scope_b)

    assert tree.find_scope_for_line(2).scope_id == "a"  # only A covers this
    assert tree.find_scope_for_line(5).scope_id == "b"  # overlap: B has larger start
    assert tree.find_scope_for_line(10).scope_id == "b"  # overlap: B has larger start
    assert tree.find_scope_for_line(13).scope_id == "b"  # only B covers this
    assert tree.find_scope_for_line(16).scope_id == "module"  # past both


def test_empty_tree_always_returns_root() -> None:
    """A tree with no non-module scopes: every query (including negative) returns root."""
    root = _make_root()
    tree = ScopeTree(root=root)
    tree.add_scope(root)

    for line in (-5, -1, 0, 1, 1000):
        assert tree.find_scope_for_line(line) is root


# Index invalidation and caching behavior.


def test_add_scope_invalidates_line_index() -> None:
    """A scope added AFTER the index was built must be visible on the next query."""
    root = _make_root()
    tree = ScopeTree(root=root)
    tree.add_scope(root)

    scope_a = _make_scope("a", start_line=0, end_line=10)
    tree.add_scope(scope_a)

    # Force the index to build.
    assert tree.find_scope_for_line(1).scope_id == "a"

    # Add a scope that should win over "a" for a subset of its range.
    scope_b = _make_scope("b", start_line=5, end_line=8)
    tree.add_scope(scope_b)

    assert tree.find_scope_for_line(6).scope_id == "b"
    assert tree.find_scope_for_line(1).scope_id == "a"


def test_get_all_function_scopes_invalidated_by_add_scope() -> None:
    """The cached function-scope list must reflect scopes added after the first read."""
    root = _make_root()
    tree = ScopeTree(root=root)
    tree.add_scope(root)

    func_a = _make_scope("func_a", start_line=0, end_line=2, scope_type=ScopeType.FUNCTION)
    tree.add_scope(func_a)

    first_read = tree.get_all_function_scopes()
    assert [s.scope_id for s in first_read] == ["func_a"]

    func_b = _make_scope("func_b", start_line=3, end_line=5, scope_type=ScopeType.FUNCTION)
    tree.add_scope(func_b)

    second_read = tree.get_all_function_scopes()
    assert [s.scope_id for s in second_read] == ["func_a", "func_b"]


def test_get_all_function_scopes_excludes_module_and_class() -> None:
    """Only FUNCTION scopes are returned, never MODULE or CLASS."""
    root = _make_root()
    tree = ScopeTree(root=root)
    tree.add_scope(root)

    cls = _make_scope("cls", start_line=0, end_line=10, scope_type=ScopeType.CLASS)
    tree.add_scope(cls)
    method = _make_scope(
        "method", start_line=1, end_line=3, scope_type=ScopeType.FUNCTION, parent=cls
    )
    tree.add_scope(method)
    nested = _make_scope(
        "nested", start_line=5, end_line=5, scope_type=ScopeType.FUNCTION, parent=cls
    )
    tree.add_scope(nested)

    scope_ids = {s.scope_id for s in tree.get_all_function_scopes()}
    assert scope_ids == {"method", "nested"}
