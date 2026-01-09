"""Tests for the type annotation insertion engine."""

from auto_type.insertion import InsertionEngine


class TestSingleVariableInsertion:
    """Test inserting type annotations for single variables."""

    def test_insert_simple_int(self) -> None:
        """Test inserting int type for simple assignment."""
        engine = InsertionEngine()
        source = "x = 42\n"

        modified, success = engine.insert_type(source, "x", "int")

        assert success
        assert modified == "x: int = 42\n"

    def test_insert_simple_str(self) -> None:
        """Test inserting str type for string assignment."""
        engine = InsertionEngine()
        source = "name = 'hello'\n"

        modified, success = engine.insert_type(source, "name", "str")

        assert success
        assert modified == "name: str = 'hello'\n"

    def test_insert_list_type(self) -> None:
        """Test inserting list type annotation."""
        engine = InsertionEngine()
        source = "items = [1, 2, 3]\n"

        modified, success = engine.insert_type(source, "items", "list[int]")

        assert success
        assert modified == "items: list[int] = [1, 2, 3]\n"

    def test_insert_dict_type(self) -> None:
        """Test inserting dict type annotation."""
        engine = InsertionEngine()
        source = "data = {'key': 'value'}\n"

        modified, success = engine.insert_type(source, "data", "dict[str, str]")

        assert success
        assert modified == "data: dict[str, str] = {'key': 'value'}\n"

    def test_preserve_formatting(self) -> None:
        """Test that formatting and spacing are preserved."""
        engine = InsertionEngine()
        source = "x   =   42  # comment\n"

        modified, success = engine.insert_type(source, "x", "int")

        assert success
        assert "# comment" in modified
        assert ": int" in modified

    def test_skip_already_annotated(self) -> None:
        """Test that variables with existing annotations are skipped."""
        engine = InsertionEngine()
        source = "x: str = 'hello'\n"

        modified, success = engine.insert_type(source, "x", "int")

        assert not success
        assert modified == source  # Unchanged
        assert "str" in modified  # Original annotation preserved

    def test_variable_not_found(self) -> None:
        """Test behavior when variable is not found in source."""
        engine = InsertionEngine()
        source = "x = 42\n"

        modified, success = engine.insert_type(source, "y", "int")

        assert not success
        assert modified == source

    def test_multiple_variables_insert_one(self) -> None:
        """Test inserting type for one variable when multiple exist."""
        engine = InsertionEngine()
        source = "x = 42\ny = 'hello'\n"

        modified, success = engine.insert_type(source, "x", "int")

        assert success
        assert "x: int = 42" in modified
        assert "y = 'hello'" in modified  # y unchanged


class TestBulkInsertion:
    """Test bulk insertion of multiple type annotations."""

    def test_bulk_insert_multiple_types(self) -> None:
        """Test inserting multiple type annotations at once."""
        engine = InsertionEngine()
        source = "x = 42\nname = 'hello'\nitems = [1, 2, 3]\n"
        types_map = {
            "x": "int",
            "name": "str",
            "items": "list[int]",
        }

        modified, result = engine.insert_types_bulk(source, types_map)

        assert result["success"]
        assert result["inserted_count"] == 3
        assert "x: int = 42" in modified
        assert "name: str = 'hello'" in modified
        assert "items: list[int] = [1, 2, 3]" in modified

    def test_bulk_insert_skip_annotated(self) -> None:
        """Test that bulk insert skips already-annotated variables."""
        engine = InsertionEngine()
        source = "x = 42\ny: str = 'hello'\nz = 3.14\n"
        types_map = {
            "x": "int",
            "y": "int",  # Already has str annotation
            "z": "float",
        }

        modified, result = engine.insert_types_bulk(source, types_map)

        assert result["success"]
        assert result["inserted_count"] == 2
        assert len(result["skipped"]) == 1
        assert "y" in result["skipped"]
        assert "x: int = 42" in modified
        assert "y: str = 'hello'" in modified  # Original preserved
        assert "z: float = 3.14" in modified

    def test_bulk_insert_empty_map(self) -> None:
        """Test bulk insert with empty types map."""
        engine = InsertionEngine()
        source = "x = 42\n"

        modified, result = engine.insert_types_bulk(source, {})

        assert not result["success"]
        assert result["inserted_count"] == 0
        assert modified == source

    def test_bulk_insert_partial_success(self) -> None:
        """Test bulk insert where some variables are not found."""
        engine = InsertionEngine()
        source = "x = 42\n"
        types_map = {
            "x": "int",
            "y": "str",  # Not in source
            "z": "float",  # Not in source
        }

        modified, result = engine.insert_types_bulk(source, types_map)

        assert result["success"]  # At least one inserted
        assert result["inserted_count"] == 1
        assert "x: int = 42" in modified


class TestPreviewInsertions:
    """Test preview functionality for type insertions."""

    def test_preview_basic(self) -> None:
        """Test basic preview of insertions."""
        engine = InsertionEngine()
        source = "x = 42\nname = 'hello'\n"
        types_map = {"x": "int", "name": "str"}

        preview = engine.preview_insertions(source, types_map)

        assert preview["success"]
        assert preview["total_changes"] == 2
        assert len(preview["will_insert"]) == 2
        assert len(preview["will_skip"]) == 0

    def test_preview_with_skips(self) -> None:
        """Test preview when some variables will be skipped."""
        engine = InsertionEngine()
        source = "x = 42\ny: str = 'hello'\n"
        types_map = {"x": "int", "y": "int"}

        preview = engine.preview_insertions(source, types_map)

        assert preview["success"]
        assert preview["total_changes"] == 1
        assert len(preview["will_insert"]) == 1
        assert len(preview["will_skip"]) == 1
        assert preview["will_skip"][0]["variable"] == "y"
        assert "Already has type annotation" in preview["will_skip"][0]["reason"]

    def test_preview_no_changes(self) -> None:
        """Test preview when no changes will be made."""
        engine = InsertionEngine()
        source = "x: int = 42\n"
        types_map = {"x": "int"}

        preview = engine.preview_insertions(source, types_map)

        assert preview["success"]
        assert preview["total_changes"] == 0
        assert len(preview["will_insert"]) == 0
        assert len(preview["will_skip"]) == 1


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_invalid_syntax(self) -> None:
        """Test handling of invalid Python syntax."""
        engine = InsertionEngine()
        source = "x = \n"  # Invalid syntax

        modified, success = engine.insert_type(source, "x", "int")

        assert not success
        assert modified == source

    def test_tuple_unpacking_not_supported(self) -> None:
        """Test that tuple unpacking is not annotated."""
        engine = InsertionEngine()
        source = "x, y = 1, 2\n"

        modified, success = engine.insert_type(source, "x", "int")

        assert not success
        assert modified == source

    def test_multiline_value(self) -> None:
        """Test insertion with multiline value."""
        engine = InsertionEngine()
        source = "data = {\n    'key': 'value'\n}\n"

        modified, success = engine.insert_type(source, "data", "dict[str, str]")

        assert success
        assert "data: dict[str, str] =" in modified
        assert "'key': 'value'" in modified

    def test_complex_type_annotation(self) -> None:
        """Test insertion of complex type annotations."""
        engine = InsertionEngine()
        source = "result = None\n"

        modified, success = engine.insert_type(source, "result", "dict[str, list[int]] | None")

        assert success
        assert "dict[str, list[int]] | None" in modified

    def test_preserve_comments_and_docstrings(self) -> None:
        """Test that comments and docstrings are preserved."""
        engine = InsertionEngine()
        source = """# This is a comment
x = 42  # inline comment
"""

        modified, success = engine.insert_type(source, "x", "int")

        assert success
        assert "# This is a comment" in modified
        assert "# inline comment" in modified
        assert "x: int = 42" in modified


class TestTypeReplacement:
    """Test replacing existing type annotations."""

    def test_replace_simple_type(self) -> None:
        """Test replacing a simple type annotation."""
        engine = InsertionEngine()
        source = "x: str = 42\n"

        modified, success = engine.replace_type(source, "x", "int")

        assert success
        assert modified == "x: int = 42\n"

    def test_replace_complex_type(self) -> None:
        """Test replacing a complex type annotation."""
        engine = InsertionEngine()
        source = "data: dict[str, str] = {'key': 42}\n"

        modified, success = engine.replace_type(source, "data", "dict[str, int]")

        assert success
        assert modified == "data: dict[str, int] = {'key': 42}\n"

    def test_replace_preserves_formatting(self) -> None:
        """Test that replacement preserves formatting and comments."""
        engine = InsertionEngine()
        source = "x: str = 42  # This is wrong\n"

        modified, success = engine.replace_type(source, "x", "int")

        assert success
        assert "x: int = 42" in modified
        assert "# This is wrong" in modified

    def test_replace_variable_not_found(self) -> None:
        """Test replacing type for non-existent variable."""
        engine = InsertionEngine()
        source = "x: int = 42\n"

        modified, success = engine.replace_type(source, "y", "str")

        assert not success
        assert modified == source

    def test_replace_unannotated_variable(self) -> None:
        """Test replacing type for variable without annotation."""
        engine = InsertionEngine()
        source = "x = 42\n"

        modified, success = engine.replace_type(source, "x", "int")

        assert not success
        assert modified == source

    def test_replace_multiple_variables_one(self) -> None:
        """Test replacing type for one variable among many."""
        engine = InsertionEngine()
        source = "x: str = 42\ny: str = 'hello'\nz: int = 3.14\n"

        modified, success = engine.replace_type(source, "z", "float")

        assert success
        assert "x: str = 42" in modified  # Unchanged
        assert "y: str = 'hello'" in modified  # Unchanged
        assert "z: float = 3.14" in modified  # Changed

    def test_replace_with_union_type(self) -> None:
        """Test replacing with a union type."""
        engine = InsertionEngine()
        source = "x: int = 42\n"

        modified, success = engine.replace_type(source, "x", "int | str")

        assert success
        assert "x: int | str = 42" in modified

    def test_replace_list_to_dict(self) -> None:
        """Test replacing list annotation with dict."""
        engine = InsertionEngine()
        source = "x: list = {}\n"

        modified, success = engine.replace_type(source, "x", "dict")

        assert success
        assert modified == "x: dict = {}\n"

    def test_replace_with_typing_module_type(self) -> None:
        """Test replacing with typing module types."""
        engine = InsertionEngine()
        source = "from typing import List\nx: str = []\n"

        modified, success = engine.replace_type(source, "x", "List[int]")

        assert success
        assert "x: List[int] = []" in modified

    def test_replace_multiline_value(self) -> None:
        """Test replacement with multiline value."""
        engine = InsertionEngine()
        source = "data: int = {\n    'key': 'value'\n}\n"

        modified, success = engine.replace_type(source, "data", "dict[str, str]")

        assert success
        assert "data: dict[str, str] =" in modified
        assert "'key': 'value'" in modified

    def test_replace_invalid_syntax(self) -> None:
        """Test handling of invalid syntax during replacement."""
        engine = InsertionEngine()
        source = "x: int = \n"  # Invalid

        modified, success = engine.replace_type(source, "x", "str")

        assert not success
        assert modified == source
