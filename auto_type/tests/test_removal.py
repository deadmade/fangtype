"""Tests for the type annotation removal engine."""

from auto_type.insertion import InsertionEngine


class TestSingleVariableRemoval:
    """Test removing type annotations for single variables."""

    def test_remove_simple_int(self) -> None:
        """Test removing int type from simple assignment."""
        engine = InsertionEngine()
        source = "x: int = 42\n"

        modified, success = engine.remove_type(source, "x")

        assert success
        assert modified == "x = 42\n"

    def test_remove_simple_str(self) -> None:
        """Test removing str type from string assignment."""
        engine = InsertionEngine()
        source = "name: str = 'hello'\n"

        modified, success = engine.remove_type(source, "name")

        assert success
        assert modified == "name = 'hello'\n"

    def test_remove_list_type(self) -> None:
        """Test removing list type annotation."""
        engine = InsertionEngine()
        source = "items: list[int] = [1, 2, 3]\n"

        modified, success = engine.remove_type(source, "items")

        assert success
        assert modified == "items = [1, 2, 3]\n"

    def test_remove_dict_type(self) -> None:
        """Test removing dict type annotation."""
        engine = InsertionEngine()
        source = "data: dict[str, str] = {'key': 'value'}\n"

        modified, success = engine.remove_type(source, "data")

        assert success
        assert modified == "data = {'key': 'value'}\n"

    def test_remove_complex_type(self) -> None:
        """Test removing complex type annotation."""
        engine = InsertionEngine()
        source = "result: dict[str, list[int]] | None = None\n"

        modified, success = engine.remove_type(source, "result")

        assert success
        assert modified == "result = None\n"

    def test_remove_union_type(self) -> None:
        """Test removing union type annotation."""
        engine = InsertionEngine()
        source = "value: int | str = 42\n"

        modified, success = engine.remove_type(source, "value")

        assert success
        assert modified == "value = 42\n"

    def test_preserve_formatting(self) -> None:
        """Test that formatting and spacing are preserved."""
        engine = InsertionEngine()
        source = "x: int   =   42  # comment\n"

        modified, success = engine.remove_type(source, "x")

        assert success
        assert "# comment" in modified
        assert "x =" in modified
        assert ": int" not in modified

    def test_preserve_comments(self) -> None:
        """Test that comments are preserved when removing types."""
        engine = InsertionEngine()
        source = "x: int = 42  # inline comment\n"

        modified, success = engine.remove_type(source, "x")

        assert success
        assert "# inline comment" in modified
        assert "x = 42" in modified

    def test_variable_not_annotated_returns_false(self) -> None:
        """Test that removal fails for non-annotated variables."""
        engine = InsertionEngine()
        source = "x = 42\n"

        modified, success = engine.remove_type(source, "x")

        assert not success
        assert modified == source

    def test_variable_not_found_returns_false(self) -> None:
        """Test behavior when variable is not found in source."""
        engine = InsertionEngine()
        source = "x: int = 42\n"

        modified, success = engine.remove_type(source, "y")

        assert not success
        assert modified == source

    def test_variable_without_value_not_removed(self) -> None:
        """Test that variable declarations without values are not removed."""
        engine = InsertionEngine()
        source = "x: int\n"

        modified, success = engine.remove_type(source, "x")

        assert not success
        assert modified == source  # Should remain unchanged
        assert "x: int" in modified

    def test_multiple_variables_remove_one(self) -> None:
        """Test removing type from one variable when multiple exist."""
        engine = InsertionEngine()
        source = "x: int = 42\ny: str = 'hello'\n"

        modified, success = engine.remove_type(source, "x")

        assert success
        assert "x = 42" in modified
        assert "y: str = 'hello'" in modified  # y unchanged


class TestBulkRemoval:
    """Test bulk removal of multiple type annotations."""

    def test_bulk_remove_all_types_in_file(self) -> None:
        """Test removing all type annotations at once."""
        engine = InsertionEngine()
        source = "x: int = 42\nname: str = 'hello'\nitems: list[int] = [1, 2, 3]\n"

        modified, result = engine.remove_types_bulk(source, None)

        assert result["success"]
        assert result["removed_count"] == 3
        assert "x = 42" in modified
        assert "name = 'hello'" in modified
        assert "items = [1, 2, 3]" in modified
        assert ": int" not in modified
        assert ": str" not in modified
        assert ": list[int]" not in modified

    def test_bulk_remove_specific_variables(self) -> None:
        """Test removing specific variable annotations."""
        engine = InsertionEngine()
        source = "x: int = 42\ny: str = 'hello'\nz: float = 3.14\n"

        modified, result = engine.remove_types_bulk(source, ["x", "z"])

        assert result["success"]
        assert result["removed_count"] == 2
        assert "x = 42" in modified
        assert "y: str = 'hello'" in modified  # y preserved
        assert "z = 3.14" in modified

    def test_bulk_remove_empty_list(self) -> None:
        """Test bulk remove with empty list."""
        engine = InsertionEngine()
        source = "x: int = 42\n"

        modified, result = engine.remove_types_bulk(source, [])

        assert not result["success"]
        assert result["removed_count"] == 0
        assert modified == source

    def test_bulk_remove_none_removes_all(self) -> None:
        """Test that None parameter removes all annotations."""
        engine = InsertionEngine()
        source = "x: int = 42\ny: str = 'test'\n"

        modified, result = engine.remove_types_bulk(source, None)

        assert result["success"]
        assert result["removed_count"] == 2
        assert ": int" not in modified
        assert ": str" not in modified

    def test_bulk_remove_partial_success(self) -> None:
        """Test bulk remove where some variables are not found."""
        engine = InsertionEngine()
        source = "x: int = 42\n"

        modified, result = engine.remove_types_bulk(source, ["x", "y", "z"])

        assert result["success"]  # At least one removed
        assert result["removed_count"] == 1
        assert len(result["not_found"]) == 2
        assert "y" in result["not_found"]
        assert "z" in result["not_found"]
        assert "x = 42" in modified

    def test_bulk_remove_mixed_annotated_unannotated(self) -> None:
        """Test bulk remove on file with mixed annotated/unannotated variables."""
        engine = InsertionEngine()
        source = "x: int = 42\ny = 'hello'\nz: float = 3.14\n"

        modified, result = engine.remove_types_bulk(source, None)

        assert result["success"]
        assert result["removed_count"] == 2
        assert "x = 42" in modified
        assert "y = 'hello'" in modified
        assert "z = 3.14" in modified

    def test_bulk_remove_skips_no_value_variables(self) -> None:
        """Test that variables without values are skipped."""
        engine = InsertionEngine()
        source = "x: int = 42\ny: str\nz: float = 3.14\n"

        modified, result = engine.remove_types_bulk(source, None)

        assert result["success"]
        assert result["removed_count"] == 2
        assert len(result["skipped"]) == 1
        assert "y" in result["skipped"]
        assert "x = 42" in modified
        assert "y: str" in modified  # Preserved
        assert "z = 3.14" in modified


class TestPreviewRemovals:
    """Test preview functionality for type removals."""

    def test_preview_all_types(self) -> None:
        """Test basic preview of removing all types."""
        engine = InsertionEngine()
        source = "x: int = 42\nname: str = 'hello'\n"

        preview = engine.preview_removals(source, None)

        assert preview["success"]
        assert preview["total_changes"] == 2
        assert len(preview["will_remove"]) == 2
        assert len(preview["will_skip"]) == 0
        assert len(preview["not_found"]) == 0

    def test_preview_specific_variables(self) -> None:
        """Test preview of removing specific variables."""
        engine = InsertionEngine()
        source = "x: int = 42\ny: str = 'hello'\nz: float = 3.14\n"

        preview = engine.preview_removals(source, ["x", "z"])

        assert preview["success"]
        assert preview["total_changes"] == 2
        assert len(preview["will_remove"]) == 2
        # Check that y is not in will_remove
        removed_vars = [item["variable"] for item in preview["will_remove"]]
        assert "x" in removed_vars
        assert "z" in removed_vars
        assert "y" not in removed_vars

    def test_preview_with_not_found(self) -> None:
        """Test preview when some variables are not found."""
        engine = InsertionEngine()
        source = "x: int = 42\n"

        preview = engine.preview_removals(source, ["x", "y"])

        assert preview["success"]
        assert preview["total_changes"] == 1
        assert len(preview["will_remove"]) == 1
        assert len(preview["not_found"]) == 1
        assert "y" in preview["not_found"]

    def test_preview_no_annotations(self) -> None:
        """Test preview when no annotations exist."""
        engine = InsertionEngine()
        source = "x = 42\ny = 'hello'\n"

        preview = engine.preview_removals(source, None)

        assert preview["success"]
        assert preview["total_changes"] == 0
        assert len(preview["will_remove"]) == 0

    def test_preview_includes_line_numbers(self) -> None:
        """Test that preview includes line number information."""
        engine = InsertionEngine()
        source = "x: int = 42\ny: str = 'hello'\n"

        preview = engine.preview_removals(source, None)

        assert preview["success"]
        for item in preview["will_remove"]:
            assert "line" in item
            assert "variable" in item
            assert "type" in item

    def test_preview_identifies_skipped_variables(self) -> None:
        """Test that preview identifies variables that will be skipped."""
        engine = InsertionEngine()
        source = "x: int = 42\ny: str\n"

        preview = engine.preview_removals(source, None)

        assert preview["success"]
        assert len(preview["will_skip"]) == 1
        assert preview["will_skip"][0]["variable"] == "y"
        assert "No value" in preview["will_skip"][0]["reason"]


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_remove_from_empty_file(self) -> None:
        """Test removal from empty file."""
        engine = InsertionEngine()
        source = ""

        modified, success = engine.remove_type(source, "x")

        assert not success
        assert modified == source

    def test_preserve_comments_and_docstrings(self) -> None:
        """Test that comments and docstrings are preserved."""
        engine = InsertionEngine()
        source = """# This is a comment
x: int = 42  # inline comment
"""

        modified, success = engine.remove_type(source, "x")

        assert success
        assert "# This is a comment" in modified
        assert "# inline comment" in modified
        assert "x = 42" in modified

    def test_multiline_values(self) -> None:
        """Test removal with multiline value."""
        engine = InsertionEngine()
        source = "data: dict[str, str] = {\n    'key': 'value'\n}\n"

        modified, success = engine.remove_type(source, "data")

        assert success
        assert "data =" in modified
        assert "'key': 'value'" in modified
        assert ": dict[str, str]" not in modified

    def test_invalid_syntax(self) -> None:
        """Test handling of invalid Python syntax."""
        engine = InsertionEngine()
        source = "x: int = \n"  # Invalid syntax

        modified, success = engine.remove_type(source, "x")

        assert not success
        assert modified == source

    def test_attribute_assignments_not_affected(self) -> None:
        """Test that attribute assignments are not affected."""
        engine = InsertionEngine()
        source = "self.x: int = 5\n"

        modified, success = engine.remove_type(source, "x")

        assert not success
        assert modified == source  # Should remain unchanged

    def test_tuple_unpacking_not_affected(self) -> None:
        """Test that tuple unpacking is not affected."""
        engine = InsertionEngine()
        source = "x, y = 1, 2\n"

        modified, success = engine.remove_type(source, "x")

        assert not success
        assert modified == source

    def test_class_level_annotations(self) -> None:
        """Test removal of class-level variable annotations."""
        engine = InsertionEngine()
        source = "x: int = 42\n"

        modified, success = engine.remove_type(source, "x")

        assert success
        assert "x = 42" in modified


class TestRoundTrip:
    """Test round-trip operations (insert then remove, remove then insert)."""

    def test_insert_then_remove_returns_original(self) -> None:
        """Test that inserting then removing returns to original."""
        engine = InsertionEngine()
        original = "x = 42\n"

        # Insert type
        with_type, success1 = engine.insert_type(original, "x", "int")
        assert success1
        assert "x: int = 42" in with_type

        # Remove type
        back_to_original, success2 = engine.remove_type(with_type, "x")
        assert success2
        assert back_to_original == original

    def test_remove_then_insert_roundtrip(self) -> None:
        """Test removing then inserting type annotation."""
        engine = InsertionEngine()
        original = "x: int = 42\n"

        # Remove type
        without_type, success1 = engine.remove_type(original, "x")
        assert success1
        assert without_type == "x = 42\n"

        # Insert type back
        back_to_original, success2 = engine.insert_type(without_type, "x", "int")
        assert success2
        assert back_to_original == original

    def test_bulk_insert_then_bulk_remove(self) -> None:
        """Test bulk operations in both directions."""
        engine = InsertionEngine()
        original = "x = 42\nname = 'hello'\n"

        # Bulk insert
        types_map = {"x": "int", "name": "str"}
        with_types, insert_result = engine.insert_types_bulk(original, types_map)
        assert insert_result["success"]

        # Bulk remove
        back_to_original, remove_result = engine.remove_types_bulk(with_types, None)
        assert remove_result["success"]
        assert back_to_original == original
