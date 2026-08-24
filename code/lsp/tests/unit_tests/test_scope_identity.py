"""Same-named sibling scopes stay distinct: scope identity is keyed by def line, not bare name."""

from fangtype.analysis import ScopeType
from fangtype.inference.jedi.engine import JediInferenceEngine

_PLATFORM_CONDITIONAL = """import sys
if sys.platform == "win32":
    def get_path():
        base = 1
        return base
else:
    def get_path():
        other = "x"
        return other
"""

_PROPERTY_PAIR = """class C:
    def __init__(self):
        self._w = 5
    @property
    def width(self):
        return self._w
    @width.setter
    def width(self, v):
        self._w = v
"""

_NESTED_VS_MODULE = """def helper():
    return 1
def outer():
    def helper():
        return "s"
    return helper()
"""


def _function_scopes(engine: JediInferenceEngine, source: str, name: str) -> list:
    """Every function scope called ``name``, ordered by def line."""
    result = engine.infer_types(source)
    return sorted(
        (
            scope
            for scope in result.scope_tree.scopes_by_id.values()
            if scope.scope_type == ScopeType.FUNCTION and scope.name == name
        ),
        key=lambda s: s.ast_node.lineno,
    )


def test_platform_conditional_siblings_each_keep_their_own_scope(engine) -> None:
    """Both ``get_path`` defs survive; one used to overwrite the other in scopes_by_id."""
    scopes = _function_scopes(engine, _PLATFORM_CONDITIONAL, "get_path")

    assert [s.ast_node.lineno for s in scopes] == [3, 7]
    # Locals from mutually-exclusive branches used to merge into one surviving scope.
    assert [sorted(s.variables) for s in scopes] == [["base"], ["other"]]


def test_property_and_setter_are_distinct_scopes(engine) -> None:
    """``@property``/``@x.setter`` share a parent and a name — only the def line separates them."""
    scopes = _function_scopes(engine, _PROPERTY_PAIR, "width")

    assert [s.ast_node.lineno for s in scopes] == [5, 8]
    # The setter's `v` must not leak into the getter's scope.
    assert "v" in scopes[1].parameters
    assert "v" not in scopes[0].parameters


def test_nested_helper_does_not_collide_with_module_level_helper(engine) -> None:
    """Guard the pre-existing good case: differing parents already yielded distinct scope_ids."""
    scopes = _function_scopes(engine, _NESTED_VS_MODULE, "helper")

    assert [s.ast_node.lineno for s in scopes] == [1, 4]


def test_same_method_name_in_different_classes_still_distinct(engine) -> None:
    """Guard the pre-existing good case: different parents never collided."""
    source = 'class A:\n    def run(self):\n        return 1\nclass B:\n    def run(self):\n        return "s"\n'
    scopes = _function_scopes(engine, source, "run")

    assert [s.ast_node.lineno for s in scopes] == [2, 5]


def test_function_name_extraction_drops_the_line_discriminator(engine) -> None:
    """scope_id carries ``@line``; the emitted annotation name must not."""
    result = engine.infer_types(_PLATFORM_CONDITIONAL)
    insertions = result.get_function_insertions()

    assert {name for _line, name in insertions} == {"get_path"}
