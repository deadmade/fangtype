"""Regression: in-place annotation lands on the correct same-line assignment (L17)."""

from ._insertion_helpers import _insert_all_variables


def test_same_line_reassignment_annotates_most_recent_binding() -> None:
    # `x = "a"; x = 5` selects the most-recent binding (int); the annotation must land on
    # `x = 5`, not splice `int` onto the earlier string assignment (`x: int = "a"`).
    source = 'x = "a"; x = 5\n'
    modified = _insert_all_variables(source, {(0, "x"): "int"})

    compile(modified, "<test>", "exec")
    assert "x: int = 5" in modified
    assert 'x: int = "a"' not in modified


def test_single_assignment_still_annotated() -> None:
    # The last-match rule must not regress the ordinary single-assignment case.
    modified = _insert_all_variables("x = 5\n", {(0, "x"): "int"})

    compile(modified, "<test>", "exec")
    assert "x: int = 5" in modified
