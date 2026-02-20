"""Test the unified insertion engine."""

from auto_type.insertion import (
    CodeLocation,
    InsertionTarget,
    TargetType,
    UnifiedInsertionEngine,
)


class TestUnifiedInsertionEngine:
    """Test cases for the UnifiedInsertionEngine."""

    def test_simple_variable_insertion(self) -> None:
        """Test basic variable annotation insertion."""
        engine = UnifiedInsertionEngine()

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
        engine = UnifiedInsertionEngine()

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
        engine = UnifiedInsertionEngine()

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
        engine = UnifiedInsertionEngine()

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
        engine = UnifiedInsertionEngine()

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
        engine = UnifiedInsertionEngine()

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
        engine = UnifiedInsertionEngine()

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
        assert "variable_assignment" in preview["plans_by_strategy"]
        assert preview["plans_by_strategy"]["variable_assignment"] == 1

    def test_convenience_methods(self) -> None:
        """Test convenience methods for common operations."""
        engine = UnifiedInsertionEngine()

        # Test variable annotation
        source = "x = 42\n"
        result = engine.insert_variable_annotation(source, "x", "int", 1)

        assert result.success
        assert result.inserted_count == 1
        assert "x: int = 42" in result.modified_source

    def test_invalid_type_annotation(self) -> None:
        """Test handling of invalid type annotations."""
        engine = UnifiedInsertionEngine()

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

    def test_empty_targets(self) -> None:
        """Test handling of empty target list."""
        engine = UnifiedInsertionEngine()

        source = "x = 42\n"
        result = engine.insert([], source)

        assert result.success
        assert result.inserted_count == 0
        assert result.modified_source == source


if __name__ == "__main__":
    # Simple manual test
    engine = UnifiedInsertionEngine()

    source = "x = 42\n"
    target = InsertionTarget(
        target_type=TargetType.VARIABLE_SIMPLE,
        location=CodeLocation(line=1, column=0),
        type_annotation="int",
        name="x",
    )

    result = engine.insert([target], source)
    print(f"Success: {result.success}")
    print(f"Inserted: {result.inserted_count}")
    print(f"Modified source:\n{result.modified_source}")

    if not result.success:
        print(f"Error: {result.error_message}")
