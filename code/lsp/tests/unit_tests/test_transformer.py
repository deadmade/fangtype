"""Regression: `_while_contains_variable` keys off real walrus (`:=`) targets, not substrings."""

from fangtype.insertion import CodeLocation, InsertionEngine, InsertionTarget, TargetType


class TestWhileWalrusDetection:
    """Declaration insertion before `while` loops must key off real walrus targets."""

    def test_real_walrus_target_gets_declaration(self) -> None:
        """A genuine `:=` target in the while condition still gets its declaration."""
        engine = InsertionEngine()

        source = "while (chunk := reader.read(1024)):\n    process(chunk)\n"
        target = InsertionTarget(
            target_type=TargetType.VARIABLE_COMPLEX,
            location=CodeLocation(line=1, column=0),
            type_annotation="bytes",
            name="chunk",
        )

        result = engine.insert([target], source)

        assert result.success
        assert result.inserted_count == 1
        assert "chunk: bytes" in result.modified_source
        assert result.modified_source.index("chunk: bytes") < result.modified_source.index("while")

    def test_name_in_call_argument_is_not_a_false_positive(self) -> None:
        """Target name as a plain call arg is not a walrus target (old substring check misfired)."""
        engine = InsertionEngine()

        source = "count = 0\nwhile is_valid(count):\n    count += 1\n"
        target = InsertionTarget(
            target_type=TargetType.VARIABLE_COMPLEX,
            location=CodeLocation(line=2, column=0),
            type_annotation="int",
            name="count",
        )

        result = engine.insert([target], source)

        assert result.success
        assert result.inserted_count == 0
        assert result.modified_source == source

    def test_name_in_string_literal_is_not_a_false_positive(self) -> None:
        """Target name in a string literal is not a walrus target (old substring check misfired)."""
        engine = InsertionEngine()

        source = 'while log("no data yet"):\n    poll()\n'
        target = InsertionTarget(
            target_type=TargetType.VARIABLE_COMPLEX,
            location=CodeLocation(line=1, column=0),
            type_annotation="str",
            name="data",
        )

        result = engine.insert([target], source)

        assert result.success
        assert result.inserted_count == 0
        assert result.modified_source == source
