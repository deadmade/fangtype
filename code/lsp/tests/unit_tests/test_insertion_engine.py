"""Test the insertion engine."""

from fangtype.inference.type_utils import normalize_type_name
from fangtype.insertion import (
    CodeLocation,
    InsertionEngine,
    InsertionTarget,
    TargetType,
)


class TestInsertionEngine:
    """Test cases for the InsertionEngine."""

    def test_simple_variable_insertion(self) -> None:
        """Test basic variable annotation insertion."""
        engine = InsertionEngine()

        source = "x = 42\n"
        target = InsertionTarget(
            target_type=TargetType.VARIABLE_SIMPLE,
            location=CodeLocation(line=1, column=0),
            type_annotation="int",
            name="x",
        )

        result = engine.insert([target], source)

        assert result.success
        assert result.inserted_count == 1
        assert "x: int = 42" in result.modified_source

    def test_function_parameter_insertion(self) -> None:
        """Test function parameter annotation insertion."""
        engine = InsertionEngine()

        source = "def func(x):\n    return x\n"
        target = InsertionTarget(
            target_type=TargetType.FUNCTION_PARAMETER,
            location=CodeLocation(line=1, column=0),
            type_annotation="int",
            name="x",
        )

        result = engine.insert([target], source)

        assert result.success
        assert result.inserted_count == 1
        assert "def func(x: int):" in result.modified_source

    def test_vararg_parameter_insertion(self) -> None:
        """Test vararg parameter annotation insertion."""
        engine = InsertionEngine()

        source = "def func(*items):\n    return items\n"
        target = InsertionTarget(
            target_type=TargetType.FUNCTION_PARAMETER,
            location=CodeLocation(line=1, column=0),
            type_annotation="tuple[int, ...]",
            name="items",
        )

        result = engine.insert([target], source)

        assert result.success
        assert result.inserted_count == 1
        assert "def func(*items: tuple[int, ...]):" in result.modified_source

    def test_kwarg_parameter_insertion(self) -> None:
        """Test kwarg parameter annotation insertion."""
        engine = InsertionEngine()

        source = "def func(**kwargs):\n    return kwargs\n"
        target = InsertionTarget(
            target_type=TargetType.FUNCTION_PARAMETER,
            location=CodeLocation(line=1, column=0),
            type_annotation="dict[str, str]",
            name="kwargs",
        )

        result = engine.insert([target], source)

        assert result.success
        assert result.inserted_count == 1
        assert "def func(**kwargs: dict[str, str]):" in result.modified_source

    def test_function_return_insertion(self) -> None:
        """Test function return type annotation insertion."""
        engine = InsertionEngine()

        source = "def func():\n    return 42\n"
        target = InsertionTarget(
            target_type=TargetType.FUNCTION_RETURN,
            location=CodeLocation(line=1, column=0),
            type_annotation="int",
            name="func",
        )

        result = engine.insert([target], source)

        assert result.success
        assert result.inserted_count == 1
        assert "def func() -> int:" in result.modified_source

    def test_bulk_variable_insertion(self) -> None:
        """Test bulk variable annotation insertion."""
        engine = InsertionEngine()

        source = "x = 42\ny = 'hello'\n"
        targets = [
            InsertionTarget(
                target_type=TargetType.VARIABLE_SIMPLE,
                location=CodeLocation(line=1, column=0),
                type_annotation="int",
                name="x",
            ),
            InsertionTarget(
                target_type=TargetType.VARIABLE_SIMPLE,
                location=CodeLocation(line=2, column=0),
                type_annotation="str",
                name="y",
            ),
        ]

        result = engine.insert(targets, source)

        assert result.success
        assert result.inserted_count == 2
        assert "x: int = 42" in result.modified_source
        assert "y: str = 'hello'" in result.modified_source

    def test_preview_insertions(self) -> None:
        """Test preview functionality."""
        engine = InsertionEngine()

        source = "x = 42\n"
        targets = [
            InsertionTarget(
                target_type=TargetType.VARIABLE_SIMPLE,
                location=CodeLocation(line=1, column=0),
                type_annotation="int",
                name="x",
            ),
        ]

        preview = engine.preview_insertions(targets, source)

        assert preview["total_plans"] == 1
        by_strategy = preview["plans_by_strategy"]
        assert isinstance(by_strategy, dict)
        assert "variable_assignment" in by_strategy
        assert by_strategy["variable_assignment"] == 1

    def test_invalid_type_annotation(self) -> None:
        """Test handling of invalid type annotations."""
        engine = InsertionEngine()

        source = "x = 42\n"
        target = InsertionTarget(
            target_type=TargetType.VARIABLE_SIMPLE,
            location=CodeLocation(line=1, column=0),
            type_annotation="int[",  # Invalid syntax
            name="x",
        )

        result = engine.insert([target], source)

        assert not result.success
        assert result.inserted_count == 0
        assert result.error_message is not None
        assert "Invalid type annotation syntax" in result.error_message

    def test_partial_insert_applies_good_skips_bad(self) -> None:
        """A bad target must not block insertion of the other, valid targets."""
        engine = InsertionEngine()

        source = "x = 42\ny = 'hello'\n"
        targets = [
            InsertionTarget(
                target_type=TargetType.VARIABLE_SIMPLE,
                location=CodeLocation(line=1, column=0),
                type_annotation="int",
                name="x",
            ),
            InsertionTarget(
                target_type=TargetType.VARIABLE_SIMPLE,
                location=CodeLocation(line=2, column=0),
                type_annotation="int[",  # Invalid syntax
                name="y",
            ),
        ]

        result = engine.insert(targets, source)

        assert result.success is True
        assert result.inserted_count == 1
        assert "x: int" in result.modified_source
        assert "y: int[" not in result.modified_source
        assert "y = 'hello'" in result.modified_source
        failed_names = [t.name for t in result.failed_targets]
        assert "y" in failed_names

    def test_empty_targets(self) -> None:
        """Test handling of empty target list."""
        engine = InsertionEngine()

        source = "x = 42\n"
        result = engine.insert([], source)

        assert result.success
        assert result.inserted_count == 0
        assert result.modified_source == source

    def test_empty_subscript_normalized_annotation_actually_inserts(self) -> None:
        """E2E: a normalized ``tuple[]``->``tuple`` annotation lands as a real insertion."""
        engine = InsertionEngine()
        normalized = normalize_type_name("tuple[]")
        assert normalized == "tuple"

        source = "x = ()\n"
        target = InsertionTarget(
            target_type=TargetType.VARIABLE_SIMPLE,
            location=CodeLocation(line=1, column=0),
            type_annotation=normalized,
            name="x",
        )

        result = engine.insert([target], source)

        assert result.success
        assert result.inserted_count == 1
        assert "x: tuple = ()" in result.modified_source
        compile(result.modified_source, "<test>", "exec")

    def test_annotation_elsewhere_does_not_block_insertion(self) -> None:
        """An annotated ``count`` on another line must not make this one a REPLACEMENT."""
        engine = InsertionEngine()

        source = "count: int = 0\n\ndef tally():\n    count = 5\n    return count\n"
        target = InsertionTarget(
            target_type=TargetType.VARIABLE_SIMPLE,
            location=CodeLocation(line=4, column=4),
            type_annotation="int",
            name="count",
        )

        result = engine.insert([target], source)

        assert result.success
        assert result.inserted_count == 1
        assert "count: int = 5" in result.modified_source

    def test_annotated_param_does_not_block_variable_insertion(self) -> None:
        """A ``def f(count: int)`` param must not poison a same-named variable elsewhere."""
        engine = InsertionEngine()

        source = "def f(count: int):\n    return count\n\ntotal = 5\ncount = 7\n"
        target = InsertionTarget(
            target_type=TargetType.VARIABLE_SIMPLE,
            location=CodeLocation(line=5, column=0),
            type_annotation="int",
            name="count",
        )

        result = engine.insert([target], source)

        assert result.success
        assert result.inserted_count == 1
        assert "count: int = 7" in result.modified_source

    def test_same_line_annotation_still_replaces(self) -> None:
        """The REPLACEMENT path stays live when the annotation is on the target's own line."""
        engine = InsertionEngine()

        source = "x: str = 42\n"
        target = InsertionTarget(
            target_type=TargetType.VARIABLE_SIMPLE,
            location=CodeLocation(line=1, column=0),
            type_annotation="int",
            name="x",
        )

        result = engine.insert([target], source)

        assert result.success
        assert result.inserted_count == 1
        assert "x: int = 42" in result.modified_source

    def test_execution_failure_is_reported_not_silent(self) -> None:
        """A plan the transformer rejects must surface in failed_targets, not vanish."""
        engine = InsertionEngine()

        # A chained assign has no single-target Assign, so the in-place apply raises.
        source = "a = b = 10\n"
        target = InsertionTarget(
            target_type=TargetType.VARIABLE_SIMPLE,
            location=CodeLocation(line=1, column=0),
            type_annotation="int",
            name="a",
        )

        result = engine.insert([target], source)

        assert result.inserted_count == 0
        assert result.modified_source == source
        assert result.failed_targets == [target]
