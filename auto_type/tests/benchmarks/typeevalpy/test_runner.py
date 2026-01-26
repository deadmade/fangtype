"""Unit tests for TypeEvalPy benchmark runner utility functions."""

import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from tests.benchmarks.typeevalpy.runner import type_matches


class TestTypeMatches:
    """Test the type_matches function with various type patterns."""

    def test_exact_match(self):
        """Test exact type matching."""
        assert type_matches("int", ["int"])
        assert type_matches("str", ["str"])
        assert type_matches("bool", ["bool"])
        assert type_matches("None", ["None"])
        assert type_matches("callable", ["callable"])

    def test_no_match(self):
        """Test that non-matching types return False."""
        assert not type_matches("int", ["str"])
        assert not type_matches("list", ["dict"])
        assert not type_matches("int", ["float"])

    def test_generic_partial_match(self):
        """Test that generic types match their specialized versions."""
        # list matches list[int], list[str], etc.
        assert type_matches("list", ["list[int]"])
        assert type_matches("list", ["list[str]"])
        assert type_matches("list", ["list[list[int]]"])

        # dict matches dict[str, int], etc.
        assert type_matches("dict", ["dict[str, int]"])
        assert type_matches("dict", ["dict[str, list[int]]"])

        # set matches set[int], etc.
        assert type_matches("set", ["set[int]"])

    def test_union_simple_match(self):
        """Test union types where one component matches expected."""
        # "int | None" should match if "int" is expected
        assert type_matches("int | None", ["int"])

        # "int | None" should match if "None" is expected
        assert type_matches("int | None", ["None"])

        # "str | None" should match if "str" is expected
        assert type_matches("str | None", ["str"])

    def test_union_no_match(self):
        """Test union types where no component matches expected."""
        assert not type_matches("int | None", ["str"])
        assert not type_matches("int | str", ["float"])
        assert not type_matches("list | dict", ["tuple"])

    def test_union_multiple_components(self):
        """Test unions with multiple non-None types."""
        # "int | str" should match if either "int" or "str" is expected
        assert type_matches("int | str", ["int"])
        assert type_matches("int | str", ["str"])
        assert type_matches("int | str", ["int", "str"])

        # "int | str | None" should match any of the three
        assert type_matches("int | str | None", ["int"])
        assert type_matches("int | str | None", ["str"])
        assert type_matches("int | str | None", ["None"])

    def test_union_with_generics(self):
        """Test union types containing generic types."""
        # "list | dict" should match "list[int]"
        assert type_matches("list | dict", ["list[int]"])

        # "list | dict" should match "dict[str, int]"
        assert type_matches("list | dict", ["dict[str, int]"])

        # "list | None" should match "list[str]"
        assert type_matches("list | None", ["list[str]"])

    def test_union_with_generics_no_match(self):
        """Test union types with generics that don't match."""
        # "list | dict" should NOT match "tuple[int]"
        assert not type_matches("list | dict", ["tuple[int]"])

        # "list | None" should NOT match "dict[str, int]"
        assert not type_matches("list | None", ["dict[str, int]"])

    def test_callable_match(self):
        """Test callable matching for function names."""
        # Specific function names should match "callable"
        assert type_matches("my_func", ["callable"])
        assert type_matches("compute", ["callable"])
        assert type_matches("process_data", ["callable"])

        # But not if they don't look like function names
        assert not type_matches("MyClass", ["callable"])  # Starts with uppercase
        assert not type_matches("123invalid", ["callable"])  # Starts with number
        assert not type_matches("func-with-dash", ["callable"])  # Contains invalid char

    def test_callable_exact_match(self):
        """Test that 'callable' matches itself exactly."""
        assert type_matches("callable", ["callable"])

    def test_multiple_expected_types(self):
        """Test matching against multiple expected types."""
        # Should match if ANY expected type matches
        assert type_matches("int", ["str", "int", "float"])
        assert type_matches("list", ["dict", "list[int]", "tuple"])

    def test_empty_expected(self):
        """Test behavior with empty expected list."""
        assert not type_matches("int", [])
        assert not type_matches("int | None", [])

    def test_union_with_spaces(self):
        """Test that union parsing handles spaces correctly."""
        # Spaces around | should be handled
        assert type_matches("int | None", ["int"])
        assert type_matches("int|None", ["int"])  # No spaces
        assert type_matches("int  |  None", ["int"])  # Extra spaces

    def test_complex_real_world_cases(self):
        """Test real-world cases from TypeEvalPy benchmark."""
        # Field sensitivity case: variable could be int or None
        assert type_matches("int | None", ["int"])

        # Function reference case: function should match callable
        assert type_matches("my_function", ["callable"])

        # Container type case: list matches list[int]
        assert type_matches("list", ["list[int]"])

        # Union with container: list | dict matches list[str]
        assert type_matches("list | dict", ["list[str]"])


class TestTypeMatchesEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_inferred_type(self):
        """Test behavior with empty inferred type."""
        assert not type_matches("", ["int"])
        assert not type_matches("", [])

    def test_union_with_empty_component(self):
        """Test union with empty component (shouldn't happen, but defensive)."""
        # "int | " should still match "int"
        assert type_matches("int | ", ["int"])

    def test_single_pipe_character(self):
        """Test that a single pipe doesn't cause issues."""
        # Should not match anything
        assert not type_matches("|", ["int"])

    def test_nested_generics(self):
        """Test matching with nested generic types."""
        # "list" should match "list[list[int]]"
        assert type_matches("list", ["list[list[int]]"])

        # "dict" should match "dict[str, list[int]]"
        assert type_matches("dict", ["dict[str, list[int]]"])

    def test_union_all_none(self):
        """Test union where all components are None (edge case)."""
        # Shouldn't happen in practice, but test it
        assert type_matches("None | None", ["None"])

    def test_case_sensitivity(self):
        """Test that matching is case-sensitive."""
        assert not type_matches("Int", ["int"])
        assert not type_matches("int", ["Int"])
        assert not type_matches("LIST", ["list"])


class TestTypeMatchesBidirectional:
    """Test bidirectional generic type matching (specific <-> generic)."""

    def test_specific_list_matches_generic_list(self):
        """Specific list types should match generic 'list' expectation."""
        assert type_matches("list[str]", ["list"])
        assert type_matches("list[int]", ["list"])
        assert type_matches("list[list[int]]", ["list"])

    def test_specific_dict_matches_generic_dict(self):
        """Specific dict types should match generic 'dict' expectation."""
        assert type_matches("dict[str, int]", ["dict"])
        assert type_matches("dict[str, list[int]]", ["dict"])
        assert type_matches("dict[int, str]", ["dict"])

    def test_specific_set_matches_generic_set(self):
        """Specific set types should match generic 'set' expectation."""
        assert type_matches("set[int]", ["set"])
        assert type_matches("set[str]", ["set"])

    def test_specific_tuple_matches_generic_tuple(self):
        """Specific tuple types should match generic 'tuple' expectation."""
        assert type_matches("tuple[int, str]", ["tuple"])
        assert type_matches("tuple[int, ...]", ["tuple"])

    def test_specific_frozenset_matches_generic_frozenset(self):
        """Specific frozenset types should match generic 'frozenset' expectation."""
        assert type_matches("frozenset[int]", ["frozenset"])

    def test_union_with_specific_generics_matches(self):
        """Union with specific generics should match generic expectation."""
        assert type_matches("list[str] | None", ["list"])
        assert type_matches("dict[str, int] | None", ["dict"])
        assert type_matches("set[int] | list[str]", ["set", "list"])

    def test_non_generic_does_not_match_generic(self):
        """Non-generic types should not match unrelated generics."""
        assert not type_matches("int", ["list"])
        assert not type_matches("str", ["dict"])
        assert not type_matches("bool", ["set"])

    def test_forward_compatibility_preserved(self):
        """Ensure original forward matching still works."""
        assert type_matches("list", ["list[int]"])
        assert type_matches("dict", ["dict[str, int]"])
        assert type_matches("set", ["set[str]"])

    def test_bidirectional_with_multiple_expected(self):
        """Test bidirectional matching with multiple expected types."""
        assert type_matches("list[str]", ["dict", "list", "set"])
        assert type_matches("dict[str, int]", ["list", "dict"])

    def test_nested_generics_extract_base(self):
        """Nested generic types should extract outer base type."""
        assert type_matches("list[list[int]]", ["list"])
        assert type_matches("dict[str, list[int]]", ["dict"])

    def test_complex_union_bidirectional(self):
        """Complex unions should work with bidirectional matching."""
        assert type_matches("list[int] | dict[str, int]", ["list"])
        assert type_matches("list[int] | dict[str, int]", ["dict"])
        assert type_matches("list[int] | dict[str, int]", ["list", "dict"])

    def test_no_false_positives_for_similar_names(self):
        """Types with similar names should not falsely match."""
        assert not type_matches("listing", ["list"])
        assert not type_matches("dictionary", ["dict"])

    def test_empty_generics_not_matched(self):
        """Malformed generic syntax should not cause false matches."""
        assert not type_matches("list[]", ["int"])
        assert type_matches("list[]", ["list"])


class TestTypeMatchesDocstringExamples:
    """Test all examples from the type_matches docstring."""

    def test_docstring_example_1(self):
        """>>> type_matches('int', ['int'])"""
        assert type_matches("int", ["int"]) is True

    def test_docstring_example_2(self):
        """>>> type_matches('int | None', ['int'])"""
        assert type_matches("int | None", ["int"]) is True

    def test_docstring_example_3(self):
        """>>> type_matches('int | str', ['int', 'str'])"""
        assert type_matches("int | str", ["int", "str"]) is True

    def test_docstring_example_4(self):
        """>>> type_matches('list', ['list[int]'])"""
        assert type_matches("list", ["list[int]"]) is True

    def test_docstring_example_5(self):
        """>>> type_matches('list[str]', ['list'])"""
        assert type_matches("list[str]", ["list"]) is True

    def test_docstring_example_6(self):
        """>>> type_matches('dict[str, int]', ['dict'])"""
        assert type_matches("dict[str, int]", ["dict"]) is True
