"""Tests for the return-hint recovery in ``benchmark/typeevalpy/fact_emitter.py``.

``emit_facts`` implements the same wrapped/nested return-resolution rule as
``resolve_hint_facts`` in ``benchmark/lsp_client/shim.py``, against the same
``func_ranges`` data, and the two are not allowed to diverge. These cases mirror
``tests/unit_tests/test_shim_hint_resolution.py``'s wrapped-signature cases so a
future edit to one rule shows up as a failure on both sides.
"""

from benchmark.typeevalpy.fact_emitter import emit_facts


def _returns(facts: list[dict]) -> list[dict]:
    return [f for f in facts if "function" in f and "parameter" not in f and "variable" not in f]


def test_single_line_return_still_resolves() -> None:
    source = "def f():\n    return 1\n"
    # The signature's ')' sits at column 6, so the anchor is 7, exactly the def line.
    hints = [(0, 7, "int", True)]

    facts = emit_facts(source, hints, [], filename="f.py")

    assert _returns(facts) == [{"file": "f.py", "line_number": 1, "function": "f", "type": ["int"]}]


def test_wrapped_signature_return_resolves_to_its_enclosing_def() -> None:
    source = "def f(\n    a,\n):\n    return 1\n"
    # The anchor lands just past the ')' on line 2 (0-based), never a def line, but line 2
    # sits inside f's own range, so the fact still carries f's def line (line_number 1).
    hints = [(2, 1, "int", True)]

    facts = emit_facts(source, hints, [], filename="f.py")

    assert _returns(facts) == [{"file": "f.py", "line_number": 1, "function": "f", "type": ["int"]}]


def test_wrapped_return_resolves_to_the_innermost_enclosing_def() -> None:
    source = (
        "def outer():\n    def inner(\n        a,\n    ):\n        return a\n    return inner(1)\n"
    )
    # The closing ')' of inner's wrapped signature lands on line 3 (0-based), inside both
    # outer's range (0-5) and inner's (1-4). inner's range is smaller, so the return belongs
    # to inner, attributed to inner's own def line (line_number 2), not outer's.
    hints = [(3, 5, "int", True)]

    facts = emit_facts(source, hints, [], filename="f.py")

    assert _returns(facts) == [
        {"file": "f.py", "line_number": 2, "function": "outer.inner", "type": ["int"]}
    ]


def test_return_with_no_enclosing_def_is_dropped() -> None:
    """A return hint at module level (no def contains its line) yields no return fact."""
    source = "x = 1\n"
    hints = [(0, 5, "int", True)]

    facts = emit_facts(source, hints, [], filename="f.py")

    assert _returns(facts) == []
