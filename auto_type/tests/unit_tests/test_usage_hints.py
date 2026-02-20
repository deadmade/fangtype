"""Tests for usage-site inlay hints."""

import asyncio

from auto_type.analysis.name_collector import NameCollector, NameLocation
from auto_type.inference.jedi_engine import JediInferenceEngine
from auto_type.utils.inlay_hint_helper import InlayHintHelper
from auto_type.utils.settings import Settings


class TestJediInferenceAtLocations:
    """Tests for JediInferenceEngine.infer_types_at_locations()."""

    def test_infers_simple_variable_type(self) -> None:
        """Test inferring type at a variable usage location."""
        source = """x = 42
y = x + 1"""
        engine = JediInferenceEngine()

        # x usage is at line 2, column 4
        results = engine.infer_types_at_locations(source, [(2, 4)])

        assert (2, 4) in results
        assert results[(2, 4)] == "int"

    def test_infers_string_type(self) -> None:
        """Test inferring string type at usage."""
        source = """name = "hello"
greeting = name.upper()"""
        engine = JediInferenceEngine()

        # name usage is at line 2, column 11
        results = engine.infer_types_at_locations(source, [(2, 11)])

        assert (2, 11) in results
        assert results[(2, 11)] == "str"

    def test_infers_list_type(self) -> None:
        """Test inferring list type at usage."""
        source = """items = [1, 2, 3]
length = len(items)"""
        engine = JediInferenceEngine()

        # items usage is at line 2, column 13
        results = engine.infer_types_at_locations(source, [(2, 13)])

        assert (2, 13) in results
        assert results[(2, 13)] == "list"

    def test_infers_multiple_locations(self) -> None:
        """Test inferring types at multiple locations."""
        source = """x = 42
y = "hello"
z = x + 1
w = y.upper()"""
        engine = JediInferenceEngine()

        # x at line 3 col 4, y at line 4 col 4
        results = engine.infer_types_at_locations(source, [(3, 4), (4, 4)])

        assert (3, 4) in results
        assert results[(3, 4)] == "int"
        assert (4, 4) in results
        assert results[(4, 4)] == "str"

    def test_empty_locations_list(self) -> None:
        """Test with empty locations list."""
        source = "x = 42"
        engine = JediInferenceEngine()

        results = engine.infer_types_at_locations(source, [])

        assert results == {}

    def test_invalid_location_returns_empty(self) -> None:
        """Test that invalid locations are silently skipped."""
        source = "x = 42"
        engine = JediInferenceEngine()

        # Line 100 doesn't exist
        results = engine.infer_types_at_locations(source, [(100, 0)])

        assert (100, 0) not in results


class TestInlayHintHelperUsageHints:
    """Tests for InlayHintHelper.generate_usage_hints()."""

    def test_generates_usage_hint(self) -> None:
        """Test generating a usage hint."""
        from auto_type.utils.settings import Settings

        helper = InlayHintHelper(NameCollector(), JediInferenceEngine(), Settings())

        usage_locations = [
            NameLocation(name="x", line=2, col=4, is_definition=False, end_col=5),
        ]
        usage_types = {(2, 4): "int"}
        declaration_positions: set[tuple[int, int]] = {(1, 0)}  # x is declared at line 1

        hints = helper.generate_usage_hints(usage_locations, usage_types, declaration_positions)

        assert len(hints) == 1
        assert hints[0].label == " int"
        assert hints[0].position.line == 1  # 0-based (line 2 - 1)
        assert hints[0].position.character == 5  # end_col

    def test_skips_declaration_position(self) -> None:
        """Test that declaration positions are skipped."""
        helper = InlayHintHelper(NameCollector(), JediInferenceEngine(), Settings())

        usage_locations = [
            NameLocation(name="x", line=1, col=0, is_definition=True, end_col=1),
        ]
        usage_types = {(1, 0): "int"}
        declaration_positions: set[tuple[int, int]] = {(1, 0)}

        hints = helper.generate_usage_hints(usage_locations, usage_types, declaration_positions)

        assert len(hints) == 0

    def test_skips_unknown_types(self) -> None:
        """Test that Unknown types are not shown."""
        helper = InlayHintHelper(NameCollector(), JediInferenceEngine(), Settings())

        usage_locations = [
            NameLocation(name="x", line=2, col=4, is_definition=False, end_col=5),
        ]
        usage_types = {(2, 4): "Unknown"}
        declaration_positions: set[tuple[int, int]] = set()

        hints = helper.generate_usage_hints(usage_locations, usage_types, declaration_positions)

        assert len(hints) == 0

    def test_skips_missing_types(self) -> None:
        """Test that locations without types are skipped."""
        helper = InlayHintHelper(NameCollector(), JediInferenceEngine(), Settings())

        usage_locations = [
            NameLocation(name="x", line=2, col=4, is_definition=False, end_col=5),
        ]
        usage_types: dict[tuple[int, int], str] = {}  # No types
        declaration_positions: set[tuple[int, int]] = set()

        hints = helper.generate_usage_hints(usage_locations, usage_types, declaration_positions)

        assert len(hints) == 0

    def test_multiple_usage_hints(self) -> None:
        """Test generating multiple usage hints."""
        helper = InlayHintHelper(NameCollector(), JediInferenceEngine(), Settings())

        usage_locations = [
            NameLocation(name="x", line=2, col=4, is_definition=False, end_col=5),
            NameLocation(name="y", line=3, col=4, is_definition=False, end_col=5),
        ]
        usage_types = {(2, 4): "int", (3, 4): "str"}
        declaration_positions: set[tuple[int, int]] = set()

        hints = helper.generate_usage_hints(usage_locations, usage_types, declaration_positions)

        assert len(hints) == 2
        labels = [h.label for h in hints]
        assert " int" in labels
        assert " str" in labels


class TestDeclarationPositions:
    """Tests for InlayHintHelper.get_declaration_positions()."""

    def test_gets_declaration_positions(self) -> None:
        """Test getting declaration positions from scope tree."""
        source = """x = 42
y = "hello"
"""
        engine = JediInferenceEngine()
        result = engine.infer_types(source)

        helper = InlayHintHelper(NameCollector(), JediInferenceEngine(), Settings())
        positions = helper.get_declaration_positions(result.scope_tree)

        # Should have positions for x and y (converted to 1-based)
        assert len(positions) >= 2


class TestIntegration:
    """Integration tests for the full usage hints flow."""

    def test_full_flow(self) -> None:
        """Test the full flow from source to hints."""
        source = """x = 42
y = x + 1
z = x * y"""
        engine = JediInferenceEngine()
        helper = InlayHintHelper(NameCollector(), JediInferenceEngine(), Settings())

        # Get inference result for declarations
        result = engine.infer_types(source)
        declaration_positions = helper.get_declaration_positions(result.scope_tree)

        # Collect usage locations
        usage_locations = NameCollector.collect_usages_only(source)

        # Infer types at usage locations
        locations_to_infer = [(loc.line, loc.col) for loc in usage_locations]
        usage_types = engine.infer_types_at_locations(source, locations_to_infer)

        # Generate hints
        hints = helper.generate_usage_hints(usage_locations, usage_types, declaration_positions)

        # Should have hints for: x (line 2), x (line 3), y (line 3)
        assert len(hints) >= 2  # At least x usages should have hints


class TestProcessUsageHints:
    """Tests for InlayHintHelper.process_usage_hints()."""

    def test_process_usage_hints_flow(self) -> None:
        """Test the process_usage_hints orchestration method."""
        source = """x = 42
y = x + 1"""
        engine = JediInferenceEngine()
        helper = InlayHintHelper(NameCollector(), JediInferenceEngine(), Settings())

        # We need inference result for scope tree
        result = engine.infer_types(source)

        hints = asyncio.run(
            helper.process_usage_hints(
                source=source,
                file_path="test.py",
                range_start_line=0,
                range_end_line=10,
                inference_result=result,
            )
        )

        # usage of x is at line 2 (1-based), so index 1
        # Hints should contain at least one hint for x
        assert len(hints) > 0
        assert " int" in hints[0].label
