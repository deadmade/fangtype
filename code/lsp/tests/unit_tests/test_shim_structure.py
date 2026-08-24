"""Tests for the TypeEvalPy adapter's AST structure walk in benchmark/lsp_client/shim.py.

The scorer matches a fact on ``(file, line_number, function, parameter, variable)``, so a
binding whose enclosing function is not recorded produces a fact that can never match, even
when its type and line are right.
"""

from benchmark.lsp_client.shim import _collect_structure


def _var_enclosing(source: str) -> dict[int, str | None]:
    return _collect_structure(source)[3]


def _attr_lines(source: str) -> dict[int, tuple[str | None, set[str]]]:
    return _collect_structure(source)[2]


def test_augmented_assignment_records_its_enclosing_function() -> None:
    """``a += 3`` binds ``a``, so the fact needs ``function``."""
    source = "def func1(a):\n    a += 3\n    a *= 2\n    return a\n"
    assert _var_enclosing(source) == {1: "func1", 2: "func1"}


def test_walrus_in_a_while_test_records_its_enclosing_function() -> None:
    """The NamedExpr sits under a BoolOp under the While test, so the walk must reach it."""
    source = (
        "def count_words(string):\n"
        "    words = string.split()\n"
        "    word_count = 0\n"
        "    while words and (word := words.pop()):\n"
        "        print(word)\n"
        "        word_count += 1\n"
        "    return word_count\n"
    )
    enclosing = _var_enclosing(source)
    assert enclosing[3] == "count_words"  # (word := ...)
    assert enclosing[5] == "count_words"  # word_count += 1


def test_walrus_in_a_comprehension_binds_in_the_enclosing_function() -> None:
    source = "def f(items):\n    out = [y for x in items if (y := x)]\n    return out\n"
    assert _var_enclosing(source)[1] == "f"


def test_module_level_augmented_assignment_has_no_enclosing_function() -> None:
    assert _var_enclosing("total = 0\ntotal += 1\n") == {0: None, 1: None}


def test_augmented_self_attribute_registers_as_an_attribute() -> None:
    """``self.n += 1`` is an attribute write, and the ground truth expects ``self.n``."""
    source = "class Cls:\n    def __next__(self):\n        self.n += 1\n        return self.n\n"
    attrs = _attr_lines(source)
    assert attrs[2] == ("Cls.__next__", {"n"})


def test_plain_assignment_still_recorded() -> None:
    """Guard that widening the node gate did not disturb the existing branch."""
    source = "def f():\n    x = 1\n    return x\n"
    assert _var_enclosing(source) == {1: "f"}


def test_for_target_still_recorded() -> None:
    source = "def f(items):\n    for i in items:\n        print(i)\n"
    assert _var_enclosing(source) == {1: "f"}
