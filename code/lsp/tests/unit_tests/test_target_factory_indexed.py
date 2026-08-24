"""Parity tests for indexed target-factory helpers."""

from fangtype.insertion import TargetType
from fangtype.insertion.target_factory import (
    build_source_index,
    detect_assignment_pattern,
    detect_assignment_pattern_indexed,
    find_assignment_target,
    find_assignment_target_indexed,
    find_function_line,
    find_function_line_indexed,
    find_variable_line,
)


def _assert_assignment_parity(source: str, name: str, line_hint_0: int | None) -> None:
    legacy = find_assignment_target(source, name, line_hint_0)
    index = build_source_index(source)
    assert index is not None
    indexed = find_assignment_target_indexed(index, name, line_hint_0)
    assert indexed == legacy


def _assert_pattern_parity(source: str, name: str, line_0: int) -> None:
    legacy = detect_assignment_pattern(source, name, line_0)
    index = build_source_index(source)
    assert index is not None
    indexed = detect_assignment_pattern_indexed(index, name, line_0)
    assert indexed == legacy


def test_assignment_parity_simple_assignment() -> None:
    source = "x = 1\ny = 2\n"
    _assert_assignment_parity(source, "x", 0)


def test_assignment_parity_tuple_unpacking() -> None:
    source = "a, b = get_values()\n"
    _assert_assignment_parity(source, "a", 0)
    _assert_pattern_parity(source, "a", 0)


def test_assignment_parity_for_iteration() -> None:
    source = "for item in seq:\n    pass\n"
    _assert_assignment_parity(source, "item", 0)
    _assert_pattern_parity(source, "item", 0)


def test_assignment_parity_augassign_and_walrus() -> None:
    source = "x = 1\nx += 2\nif (word := 'hello'):\n    pass\n"
    _assert_assignment_parity(source, "x", 1)
    _assert_pattern_parity(source, "x", 1)
    _assert_assignment_parity(source, "word", 2)
    _assert_pattern_parity(source, "word", 2)


def test_assignment_parity_comprehension_iteration() -> None:
    source = "x, y = (i for i in range(3))\n"
    _assert_assignment_parity(source, "i", 0)
    _assert_pattern_parity(source, "i", 0)


def test_assignment_parity_attribute_assignment() -> None:
    source = "self.value = other.attr\n"
    _assert_assignment_parity(source, "self.value", 0)
    _assert_pattern_parity(source, "self.value", 0)


def test_assignment_parity_subscript_rhs() -> None:
    source = "value = data['k']\n"
    _assert_assignment_parity(source, "value", 0)
    _assert_pattern_parity(source, "value", 0)


def test_attribute_augassign_prefers_plain_assignment_candidate() -> None:
    source = "self.n = 0\nself.n += 1\n"
    index = build_source_index(source)
    assert index is not None

    resolved = find_assignment_target_indexed(index, "self.n", 1)
    assert resolved is not None
    assert resolved.line_1_based == 1
    assert resolved.target_type == TargetType.ATTRIBUTE_ACCESS


def test_augassign_prefers_earlier_plain_assignment_in_same_scope() -> None:
    """The accumulator idiom must annotate `total = 0`, not splice a declaration in the loop.

    Regression for the declaration-splice defect: the newest binding of `total` is the `+=`,
    which forces a DECLARATION above a line *inside* the loop body, and mypy then reports
    `no-redef` against the plain assignment above it.
    """
    source = "def subtotal(cart):\n    total = 0\n    for name in cart:\n        total += cart[name]\n    return total\n"
    index = build_source_index(source)
    assert index is not None

    resolved = find_assignment_target_indexed(index, "total", 3)
    assert resolved is not None
    assert resolved.line_1_based == 2
    assert resolved.target_type == TargetType.VARIABLE_SIMPLE


def test_augassign_preference_does_not_cross_a_function_boundary() -> None:
    """`assignment_candidates_by_name` is keyed by bare name file-wide, so preferring an
    earlier binding must not reach into another function that reuses the name."""
    source = (
        "def f():\n"
        "    total = 0\n"
        "    total += 1\n"
        "    return total\n"
        "\n"
        "def g():\n"
        "    total = 0\n"
        "    total += 2\n"
        "    return total\n"
    )
    index = build_source_index(source)
    assert index is not None

    resolved = find_assignment_target_indexed(index, "total", 7)
    assert resolved is not None
    assert resolved.line_1_based == 7
    assert resolved.target_type == TargetType.VARIABLE_SIMPLE


def test_walrus_prefers_earlier_plain_assignment() -> None:
    source = "word = ''\nif (word := compute()):\n    pass\n"
    index = build_source_index(source)
    assert index is not None

    resolved = find_assignment_target_indexed(index, "word", 1)
    assert resolved is not None
    assert resolved.line_1_based == 1
    assert resolved.target_type == TargetType.VARIABLE_SIMPLE


def test_walrus_without_prior_assignment_keeps_its_declaration() -> None:
    source = "if (word := compute()):\n    pass\n"
    index = build_source_index(source)
    assert index is not None

    resolved = find_assignment_target_indexed(index, "word", 0)
    assert resolved is not None
    assert resolved.line_1_based == 1
    assert resolved.target_type == TargetType.VARIABLE_COMPLEX


def test_iteration_variable_prefers_earlier_plain_assignment() -> None:
    """A loop target that rebinds an existing name would also earn `no-redef`."""
    source = "item = first()\nfor item in seq:\n    use(item)\n"
    index = build_source_index(source)
    assert index is not None

    resolved = find_assignment_target_indexed(index, "item", 1)
    assert resolved is not None
    assert resolved.line_1_based == 1
    assert resolved.target_type == TargetType.VARIABLE_SIMPLE


def test_bare_loop_target_still_declares_above_the_for() -> None:
    source = "for item in seq:\n    use(item)\n"
    index = build_source_index(source)
    assert index is not None

    resolved = find_assignment_target_indexed(index, "item", 0)
    assert resolved is not None
    assert resolved.line_1_based == 1
    assert resolved.target_type == TargetType.ITERATION_VARIABLE


def test_declaration_without_an_inplace_candidate_uses_the_earliest_binding() -> None:
    """With only declaration-forcing bindings the declaration goes above the first of them,
    never above a later one that an earlier binding already precedes."""
    source = (
        "def f(seq):\n    for total in seq:\n        pass\n    for total in seq:\n        pass\n"
    )
    index = build_source_index(source)
    assert index is not None

    resolved = find_assignment_target_indexed(index, "total", 3)
    assert resolved is not None
    assert resolved.line_1_based == 2
    assert resolved.target_type == TargetType.ITERATION_VARIABLE


def test_assignment_uses_line_hint_at_or_before() -> None:
    source = "x = 1\nx = 2\nx = 3\n"
    index = build_source_index(source)
    assert index is not None

    resolved = find_assignment_target_indexed(index, "x", 1)
    assert resolved is not None
    assert resolved.line_1_based == 2


def test_find_function_line_indexed_parity() -> None:
    source = """
def outer():
    def inner():
        return 1

class A:
    async def work(self):
        return 2
"""
    index = build_source_index(source)
    assert index is not None

    assert find_function_line_indexed(index, "outer.inner") == find_function_line(
        source, "outer.inner"
    )
    assert find_function_line_indexed(index, "A.work") == find_function_line(source, "A.work")
    assert find_function_line_indexed(index, "work") == find_function_line(source, "work")


def test_index_none_on_syntax_error_and_legacy_fallback() -> None:
    source = "invalid syntax [["
    assert build_source_index(source) is None
    # VARIABLE_SIMPLE syntax-error fallback: see test_new_strategies.py TestPatternDetectionHelpers.
    assert find_function_line(source, "func") == 1


def test_find_variable_line_ignores_equality_comparison_collision() -> None:
    """Regression (06636b3): naive `{name} =` scan must not match `count == 5`."""
    source = (
        "def f(count=0):\n"
        "    if count == 5:\n"
        "        pass\n"
        '    result = helper(other="count = 1")\n'
        "    count = compute()\n"
        "    return count\n"
    )
    assert find_variable_line(source, "count") == 5


def test_find_variable_line_ignores_rhs_string_occurrence() -> None:
    """A name in another line's RHS string must not be mistaken for its own assignment site."""
    source = 'result = "value = 1"\nvalue = 2\n'
    assert find_variable_line(source, "value") == 2


def test_find_variable_line_no_assignment_candidate_falls_back_to_one() -> None:
    """A name bound only via an untracked form (`except as`) falls back to `1`."""
    source = "try:\n    pass\nexcept Exception as err:\n    log(err)\n"
    assert find_variable_line(source, "err") == 1


def test_find_variable_line_syntax_error_fallback_still_guards_equality() -> None:
    """On unparseable source the text-scan fallback must still reject an `==` comparison."""
    source = "invalid syntax [[\ncount == 5\ncount = compute()\n"
    assert build_source_index(source) is None
    assert find_variable_line(source, "count") == 3


def test_find_variable_line_fallback_matches_chained_assignment_target() -> None:
    """Regression (#15): startswith fallback still finds `b` in chained `a = b = 10`."""
    source = "invalid syntax [[\na = b = 10\n"
    assert build_source_index(source) is None
    assert find_variable_line(source, "b") == 2


def test_find_variable_line_fallback_ignores_equality_comparison_no_real_assignment() -> None:
    """Guard: `==` must not false-match when no real `name =` binding exists."""
    source = "invalid syntax [[\nif x == y:\n    pass\n"
    assert build_source_index(source) is None
    assert find_variable_line(source, "x") == 1


def test_find_variable_line_fallback_ignores_partial_name_match() -> None:
    """Guard: word-boundary regex must not match a name that is a substring of `foo_b`."""
    source = "invalid syntax [[\nfoo_b = 1\n"
    assert build_source_index(source) is None
    assert find_variable_line(source, "b") == 1


def test_find_variable_line_ast_path_still_resolves_chained_assignment() -> None:
    """Sanity: AST path resolves chained-assignment targets on parseable source."""
    source = "a = b = 10\n"
    assert build_source_index(source) is not None
    assert find_variable_line(source, "b") == 1
