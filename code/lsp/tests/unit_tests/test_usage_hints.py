"""Tests for usage-site inlay hints."""

import asyncio
import threading
from typing import TYPE_CHECKING, cast

from fangtype.analysis.name_collector import NameCollector, NameLocation
from fangtype.inference.jedi.engine import JediInferenceEngine
from fangtype.utils.inlay_hint_helper import InlayHintHelper
from fangtype.utils.settings import Settings

if TYPE_CHECKING:
    from fangtype.protocols import InferenceEngineProtocol


class TestJediInferenceAtLocations:
    """Tests for JediInferenceEngine.infer_types_at_locations()."""

    def test_infers_simple_variable_type(self) -> None:
        """Test inferring type at a variable usage location."""
        source = """x = 42
y = x + 1"""
        engine = JediInferenceEngine(Settings())

        # x usage is at line 2, column 4
        results = engine.infer_types_at_locations(source, [(2, 4)])

        assert (2, 4) in results
        assert results[(2, 4)] == "int"

    def test_infers_string_type(self) -> None:
        """Test inferring string type at usage."""
        source = """name = "hello"
greeting = name.upper()"""
        engine = JediInferenceEngine(Settings())

        # name usage is at line 2, column 11
        results = engine.infer_types_at_locations(source, [(2, 11)])

        assert (2, 11) in results
        assert results[(2, 11)] == "str"

    def test_infers_list_type(self) -> None:
        """Test inferring list type at usage."""
        source = """items = [1, 2, 3]
length = len(items)"""
        engine = JediInferenceEngine(Settings())

        # items usage is at line 2, column 13
        results = engine.infer_types_at_locations(source, [(2, 13)])

        assert (2, 13) in results
        # Element type is recovered from the literal, not dropped to a bare `list`.
        assert results[(2, 13)] == "list[int]"

    def test_infers_multiple_locations(self) -> None:
        """Test inferring types at multiple locations."""
        source = """x = 42
y = "hello"
z = x + 1
w = y.upper()"""
        engine = JediInferenceEngine(Settings())

        # x at line 3 col 4, y at line 4 col 4
        results = engine.infer_types_at_locations(source, [(3, 4), (4, 4)])

        assert (3, 4) in results
        assert results[(3, 4)] == "int"
        assert (4, 4) in results
        assert results[(4, 4)] == "str"

    def test_empty_locations_list(self) -> None:
        """Test with empty locations list."""
        source = "x = 42"
        engine = JediInferenceEngine(Settings())

        results = engine.infer_types_at_locations(source, [])

        assert results == {}

    def test_invalid_location_returns_empty(self) -> None:
        """Test that invalid locations are silently skipped."""
        source = "x = 42"
        engine = JediInferenceEngine(Settings())

        # Line 100 doesn't exist
        results = engine.infer_types_at_locations(source, [(100, 0)])

        assert (100, 0) not in results


class TestInlayHintHelperUsageHints:
    """Tests for InlayHintHelper.generate_usage_hints()."""

    def test_generates_usage_hint(self) -> None:
        """Test generating a usage hint."""
        from fangtype.utils.settings import Settings

        helper = InlayHintHelper(NameCollector(), JediInferenceEngine(Settings()), Settings())

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

    def test_usage_hint_column_converted_to_utf16(self) -> None:
        """Astral char (😀 = 2 UTF-16 units) left of usage shifts code-point col 11 to LSP 12."""
        helper = InlayHintHelper(NameCollector(), JediInferenceEngine(Settings()), Settings())

        source = 's = "😀"; ab'  # 'ab' spans code points 9..11
        usage_locations = [
            NameLocation(name="ab", line=1, col=9, is_definition=False, end_col=11),
        ]
        usage_types = {(1, 9): "int"}
        declaration_positions: set[tuple[int, int]] = set()

        hints = helper.generate_usage_hints(
            usage_locations, usage_types, declaration_positions, source
        )

        assert len(hints) == 1
        assert hints[0].position.character == 12  # code-point 11 -> UTF-16 12

    def test_usage_hint_column_unchanged_without_source(self) -> None:
        """Without ``source`` the code-point column passes through (ASCII-correct)."""
        helper = InlayHintHelper(NameCollector(), JediInferenceEngine(Settings()), Settings())

        usage_locations = [
            NameLocation(name="ab", line=1, col=9, is_definition=False, end_col=11),
        ]
        hints = helper.generate_usage_hints(usage_locations, {(1, 9): "int"}, set())

        assert len(hints) == 1
        assert hints[0].position.character == 11

    def test_skips_declaration_position(self) -> None:
        """Test that declaration positions are skipped."""
        helper = InlayHintHelper(NameCollector(), JediInferenceEngine(Settings()), Settings())

        usage_locations = [
            NameLocation(name="x", line=1, col=0, is_definition=True, end_col=1),
        ]
        usage_types = {(1, 0): "int"}
        declaration_positions: set[tuple[int, int]] = {(1, 0)}

        hints = helper.generate_usage_hints(usage_locations, usage_types, declaration_positions)

        assert len(hints) == 0

    def test_skips_unknown_types(self) -> None:
        """Test that Unknown types are not shown."""
        helper = InlayHintHelper(NameCollector(), JediInferenceEngine(Settings()), Settings())

        usage_locations = [
            NameLocation(name="x", line=2, col=4, is_definition=False, end_col=5),
        ]
        usage_types = {(2, 4): "Unknown"}
        declaration_positions: set[tuple[int, int]] = set()

        hints = helper.generate_usage_hints(usage_locations, usage_types, declaration_positions)

        assert len(hints) == 0

    def test_skips_missing_types(self) -> None:
        """Test that locations without types are skipped."""
        helper = InlayHintHelper(NameCollector(), JediInferenceEngine(Settings()), Settings())

        usage_locations = [
            NameLocation(name="x", line=2, col=4, is_definition=False, end_col=5),
        ]
        usage_types: dict[tuple[int, int], str] = {}  # No types
        declaration_positions: set[tuple[int, int]] = set()

        hints = helper.generate_usage_hints(usage_locations, usage_types, declaration_positions)

        assert len(hints) == 0

    def test_multiple_usage_hints(self) -> None:
        """Test generating multiple usage hints."""
        helper = InlayHintHelper(NameCollector(), JediInferenceEngine(Settings()), Settings())

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
        engine = JediInferenceEngine(Settings())
        result = engine.infer_types(source)

        helper = InlayHintHelper(NameCollector(), JediInferenceEngine(Settings()), Settings())
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
        engine = JediInferenceEngine(Settings())
        helper = InlayHintHelper(NameCollector(), JediInferenceEngine(Settings()), Settings())

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

    def test_reads_are_hinted_whether_or_not_the_binding_is_annotated(self) -> None:
        """Was M30 (an annotation in one scope hiding another scope's `data`).

        Nothing suppresses by name any more, so that class of bug is structurally impossible and
        both reads carry a hint, including the one whose binding is annotated.
        """
        source = """import json


def parse_config(raw):
    data: dict = json.loads(raw)
    return data


def compute_stats(items):
    data = [1, 2]
    return sum(data)
"""
        engine = JediInferenceEngine(Settings())
        helper = InlayHintHelper(NameCollector(), engine, Settings())

        result = engine.infer_types(source)
        declaration_positions = helper.get_declaration_positions(result.scope_tree)
        usage_locations = [
            loc for loc in NameCollector.collect_usages_only(source) if loc.name == "data"
        ]
        usage_types = {(loc.line, loc.col): "list[int]" for loc in usage_locations}

        hints = helper.generate_usage_hints(
            usage_locations, usage_types, declaration_positions, source
        )

        # Line 6 reads parse_config's annotated `data`, line 11 compute_stats' unannotated one.
        hinted_lines = {hint.position.line + 1 for hint in hints}
        assert 6 in hinted_lines
        assert 11 in hinted_lines

    def test_read_of_an_annotated_binding_is_hinted_but_the_binding_line_is_not(self) -> None:
        """`size: int = 0` needs no hint of its own, and `return size` still gets one."""
        source = "def widen():\n    size: int = 0\n    return size\n"
        engine = JediInferenceEngine(Settings())
        helper = InlayHintHelper(NameCollector(), engine, Settings())

        result = engine.infer_types(source)
        hints = asyncio.run(
            helper.process_usage_hints(source, None, 0, len(source.splitlines()), result)
        )

        hinted = {(h.position.line, h.label) for h in hints}
        assert (2, " int") in hinted, f"expected an int hint on `return size`, got: {hints}"
        assert not [h for h in hints if h.position.line == 1], (
            f"the annotated binding line must stay unhinted, got: {hints}"
        )

    def test_shadowed_local_reports_its_own_type_not_the_outer_annotation(self) -> None:
        """The outward name walk gave the local `width` the module-level `width: int`'s hint.

        Resolving at the read position instead reports the local float, so the hint is both
        present and correct.
        """
        source = "width: int = 0\n\n\ndef stretch():\n    width = 1.5\n    return width\n"
        engine = JediInferenceEngine(Settings())
        helper = InlayHintHelper(NameCollector(), engine, Settings())

        result = engine.infer_types(source)
        hints = asyncio.run(
            helper.process_usage_hints(source, None, 0, len(source.splitlines()), result)
        )

        read_hints = [h for h in hints if h.position.line == 5]
        assert read_hints, f"expected a hint on `return width`, got: {hints}"
        assert read_hints[0].label == " float", (
            f"the local float must win over the module-level `width: int`, got: {read_hints[0]}"
        )


class TestProcessUsageHints:
    """Tests for InlayHintHelper.process_usage_hints()."""

    def test_process_usage_hints_flow(self) -> None:
        """Test the process_usage_hints orchestration method."""
        source = """x = 42
y = x + 1"""
        engine = JediInferenceEngine(Settings())
        helper = InlayHintHelper(NameCollector(), JediInferenceEngine(Settings()), Settings())

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

        # x is used on line 2 (1-based), so at least one hint for x must come back.
        assert len(hints) > 0
        assert " int" in hints[0].label

    def test_process_usage_hints_infers_off_main_thread(self) -> None:
        """The Jedi usage-location inference (site 2) must run off the event loop."""
        source = """x = 42
y = x + 1"""
        real_engine = JediInferenceEngine(Settings())
        inference_result = real_engine.infer_types(source)

        thread_flags: dict[str, bool] = {}

        class RecordingEngine:
            def infer_types_at_locations(
                self,
                source: str,
                locations: list[tuple[int, int]],
                file_path: str | None,
                cancel_token: object | None = None,
            ) -> dict[tuple[int, int], str]:
                thread_flags["is_main"] = threading.current_thread() is threading.main_thread()
                return real_engine.infer_types_at_locations(source, locations, file_path)

        helper = InlayHintHelper(
            NameCollector(), cast("InferenceEngineProtocol", RecordingEngine()), Settings()
        )

        hints = asyncio.run(
            helper.process_usage_hints(
                source=source,
                file_path="test.py",
                range_start_line=0,
                range_end_line=10,
                inference_result=inference_result,
            )
        )

        assert "is_main" in thread_flags, "infer_types_at_locations was never called"
        assert thread_flags["is_main"] is False
        assert len(hints) > 0
