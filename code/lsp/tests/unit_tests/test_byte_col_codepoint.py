"""Issue #8: ast byte col_offset vs code-point cols diverge with non-ASCII left; pin both."""

import ast

import jedi

from fangtype.analysis.types import Scope
from fangtype.inference.jedi.positions import script_byte_col_to_codepoint
from fangtype.inference.jedi.probe import JediProbe
from fangtype.inference.jedi.scope_builder import build_scope_tree
from fangtype.utils.position_encoding import byte_to_codepoint


def _last_assign_value(source: str) -> ast.expr:
    tree = ast.parse(source)
    return [n for n in ast.walk(tree) if isinstance(n, ast.Assign)][-1].value


def _iter_scopes(scope: Scope):
    yield scope
    for child in scope.children:
        yield from _iter_scopes(child)


# --- helper unit tests -----------------------------------------------------------------


def test_helper_converts_multibyte_byte_col_to_codepoint():
    # ``ä`` is 2 UTF-8 bytes, so a byte column past it is one greater than the code point.
    script = jedi.Script(code="ä = value\n")
    # 'ä = ' -> byte col 5 == code-point col 4 (one multibyte char to the left).
    assert script_byte_col_to_codepoint(script, 1, 5) == 4


def test_helper_falls_back_to_byte_col_when_line_unavailable():
    script = jedi.Script(code="x = 1\n")
    # Out-of-range line -> raw byte offset (mirrors name_collector fallback contract).
    assert script_byte_col_to_codepoint(script, 99, 7) == 7


# --- Jedi infer sites ------------------------------------------------------------------


def test_probe_infers_expr_after_leading_non_ascii():
    # RED pre-fix: multibyte chars shift byte cols past code-point cols so infer missed the BinOp.
    source = "öäü = 5; nörf = öäü + 1\n"
    script = jedi.Script(code=source)
    expr = _last_assign_value(source)  # the ``öäü + 1`` BinOp
    assert JediProbe(script).infer_expr_type(expr) == "int"


# --- AST-sourced TypeInfo.col storage sites --------------------------------------------


def test_function_call_assignment_stores_codepoint_col():
    # FUNCTION_CALL storage guard (scope_builder ~612): ``result`` col is code-point 4 not byte 5.
    source = "def make():\n    return 5\n\nä = result = make()\n"
    script = jedi.Script(code=source)
    tree = ast.parse(source)
    scope_tree = build_scope_tree(script, tree, enable_cross_file=False)

    info = scope_tree.root.variables["result"]
    assert info.type_str == "int"

    line = source.splitlines()[3]
    target = [
        t
        for n in ast.walk(tree)
        if isinstance(n, ast.Assign)
        for t in n.targets
        if isinstance(t, ast.Name) and t.id == "result"
    ][0]
    expected_cp = byte_to_codepoint(line, target.col_offset)
    assert expected_cp != target.col_offset  # byte != code point (proves the fixture bites)
    assert info.col == expected_cp


def test_self_attribute_stores_codepoint_col():
    # ``self.width`` sits after a leading non-ASCII char; its stored col must be code-point.
    source = "class C:\n    def __init__(self, w):\n        ä = self.width = w\n"
    script = jedi.Script(code=source)
    tree = ast.parse(source)
    scope_tree = build_scope_tree(script, tree, enable_cross_file=False)

    line = source.splitlines()[2]
    attr = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute)][0]
    expected_cp = byte_to_codepoint(line, attr.col_offset)
    assert expected_cp != attr.col_offset  # byte (13) != code point (12)

    for scope in _iter_scopes(scope_tree.root):
        if "width" in scope.attributes:
            assert scope.attributes["width"].col == expected_cp


# --- override inference (shared helper, correctness maintained) -------------------------


def test_override_inference_through_non_ascii_base_name():
    # Base ``Bäse`` has a multibyte char; override must still adopt base sig (value: int, -> str).
    source = (
        "class Bäse:\n"
        "    def run(self, value: int) -> str:\n"
        '        return ""\n'
        "\n"
        "class Sub(Bäse):\n"
        "    def run(self, value):\n"
        '        return ""\n'
    )
    script = jedi.Script(code=source)
    tree = ast.parse(source)
    scope_tree = build_scope_tree(script, tree, enable_cross_file=False)

    for scope in _iter_scopes(scope_tree.root):
        if scope.name == "run" and scope.parent is not None and scope.parent.name == "Sub":
            assert scope.parameters["value"].type_str == "int"
            assert scope.return_type is not None
            assert scope.return_type.type_str == "str"
            break
    else:  # pragma: no cover - scope must exist
        raise AssertionError("Sub.run scope not found")
