"""Annotations naming a class not yet bound must be written as forward references.

Pre-3.14 a signature is evaluated where the ``def`` stands, so an unbound name there raises
NameError on import. mypy accepts the broken form, which is why this needs its own gate.
"""

from fangtype.analysis import build_forward_ref_context, quote_annotation
from fangtype.analysis.forward_refs import is_quoted


class TestNeedsQuoting:
    """Which annotation sites would fail to evaluate."""

    def test_method_annotated_with_its_own_class(self):
        source = "class Node:\n    def link(self, other):\n        return other\n"
        ctx = build_forward_ref_context(source)

        assert ctx.needs_quoting("Node", 2) is True

    def test_return_annotated_with_enclosing_class(self):
        source = "class Node:\n    def copy(self):\n        return Node()\n"
        ctx = build_forward_ref_context(source)

        assert ctx.needs_quoting("Node", 2) is True

    def test_module_function_naming_a_later_class(self):
        source = "def wrap(item):\n    return item\n\n\nclass Later:\n    pass\n"
        ctx = build_forward_ref_context(source)

        assert ctx.needs_quoting("Later", 1) is True

    def test_class_defined_before_the_def_is_left_alone(self):
        source = "class Early:\n    pass\n\n\ndef use(e):\n    return e\n"
        ctx = build_forward_ref_context(source)

        assert ctx.needs_quoting("Early", 5) is False

    def test_imported_name_is_left_alone(self):
        source = "from decimal import Decimal\n\n\ndef use(d):\n    return d\n"
        ctx = build_forward_ref_context(source)

        assert ctx.needs_quoting("Decimal", 4) is False

    def test_builtin_is_left_alone(self):
        source = "def add(a, b):\n    return a + b\n"
        ctx = build_forward_ref_context(source)

        assert ctx.needs_quoting("int", 1) is False

    def test_class_local_to_a_function_is_never_module_visible(self):
        """``make`` sits at module level, so it can never evaluate a name local to itself."""
        source = "def make():\n    class Inner:\n        pass\n    return Inner()\n"
        ctx = build_forward_ref_context(source)

        assert ctx.needs_quoting("Inner", 1) is True

    def test_class_nested_in_a_function_still_shadows_its_own_methods(self):
        source = (
            "def make():\n"
            "    class Inner:\n"
            "        def g(self):\n"
            "            return self\n"
            "    return Inner()\n"
        )
        ctx = build_forward_ref_context(source)

        assert ctx.needs_quoting("Inner", 3) is True

    def test_annotation_inside_a_function_body_is_never_evaluated(self):
        source = "def f():\n    x = None\n    return x\n\n\nclass Later:\n    pass\n"
        ctx = build_forward_ref_context(source)

        assert ctx.needs_quoting("Later", 2) is False

    def test_subscripted_type_carrying_an_unbound_name(self):
        source = "def collect(items):\n    return items\n\n\nclass Item:\n    pass\n"
        ctx = build_forward_ref_context(source)

        assert ctx.needs_quoting("list[Item]", 1) is True

    def test_subscripted_type_of_bound_names_only(self):
        source = "def collect(items):\n    return items\n"
        ctx = build_forward_ref_context(source)

        assert ctx.needs_quoting("dict[str, int]", 1) is False

    def test_dotted_name_resolves_through_its_root(self):
        """``mod.Thing`` looks up ``mod`` alone, so an imported module needs no quoting."""
        source = "import collections\n\n\ndef use(d):\n    return d\n"
        ctx = build_forward_ref_context(source)

        assert ctx.needs_quoting("collections.OrderedDict", 4) is False

    def test_already_quoted_annotation_is_not_quoted_twice(self):
        source = "class Node:\n    def link(self, other):\n        return other\n"
        ctx = build_forward_ref_context(source)

        assert ctx.needs_quoting('"Node"', 2) is False

    def test_unparseable_module_yields_an_inert_context(self):
        ctx = build_forward_ref_context("def broken(:\n")

        assert ctx.needs_quoting("Whatever", 1) is False


class TestQuoteIfNeeded:
    """The string handed to the insertion stage."""

    def test_wraps_only_when_required(self):
        source = "class Node:\n    def link(self, other):\n        return other\n"
        ctx = build_forward_ref_context(source)

        assert ctx.quote_if_needed("Node", 2) == '"Node"'
        assert ctx.quote_if_needed("int", 2) == "int"

    def test_wraps_the_whole_subscripted_expression(self):
        source = "def collect(items):\n    return items\n\n\nclass Item:\n    pass\n"
        ctx = build_forward_ref_context(source)

        assert ctx.quote_if_needed("list[Item]", 1) == '"list[Item]"'


class TestQuoteAnnotation:
    """Quote-style selection, so the result always parses."""

    def test_prefers_double_quotes(self):
        assert quote_annotation("Node") == '"Node"'

    def test_falls_back_to_single_quotes(self):
        assert quote_annotation('Literal["a"]') == "'Literal[\"a\"]'"

    def test_leaves_a_type_carrying_both_quote_styles_alone(self):
        both = "Literal[\"a\", 'b']"

        assert quote_annotation(both) == both

    def test_result_is_recognised_as_quoted(self):
        assert is_quoted(quote_annotation("Node")) is True
        assert is_quoted("Node") is False
        assert is_quoted("list[Node]") is False
