"""Integration tests for type removal functionality."""

import pytest

from auto_type.inference import LiteralInferenceEngine
from auto_type.insertion import InsertionEngine
from auto_type.validation import TypeValidator


class TestEndToEndRemoval:
    """Test the complete workflow for type removal."""

    def test_simple_removal_workflow(self) -> None:
        """Test complete removal workflow: remove all types."""
        # Setup
        source = "x: int = 42\nname: str = 'hello'\nitems: list = [1, 2, 3]\n"
        
        insertion_engine = InsertionEngine()

        # Remove all types
        modified, result = insertion_engine.remove_types_bulk(source, None)
        
        assert result["success"]
        assert result["removed_count"] == 3
        assert "x = 42" in modified
        assert "name = 'hello'" in modified
        assert "items = [1, 2, 3]" in modified
        assert ": int" not in modified
        assert ": str" not in modified
        assert ": list" not in modified

    def test_selective_removal_workflow(self) -> None:
        """Test removing specific type annotations."""
        source = "x: int = 42\ny: str = 'hello'\nz: float = 3.14\n"
        
        insertion_engine = InsertionEngine()

        # Remove only x and z, keep y
        modified, result = insertion_engine.remove_types_bulk(source, ["x", "z"])
        
        assert result["success"]
        assert result["removed_count"] == 2
        assert "x = 42" in modified
        assert "y: str = 'hello'" in modified  # y preserved
        assert "z = 3.14" in modified

    def test_removal_with_mixed_variables(self) -> None:
        """Test removal on file with mixed annotated/unannotated variables."""
        source = "x: int = 42\ny = 'hello'\nz: float = 3.14\n"
        
        insertion_engine = InsertionEngine()

        # Remove all (should only affect x and z)
        modified, result = insertion_engine.remove_types_bulk(source, None)
        
        assert result["success"]
        assert result["removed_count"] == 2
        assert "x = 42" in modified
        assert "y = 'hello'" in modified
        assert "z = 3.14" in modified

    def test_removal_preserves_code_structure(self) -> None:
        """Test that removal preserves comments and formatting."""
        source = """# Module comment
x: int = 42  # inline comment
name: str = 'test'

# Function below
def foo():
    pass
"""
        
        insertion_engine = InsertionEngine()

        # Remove all types
        modified, result = insertion_engine.remove_types_bulk(source, None)
        
        assert result["success"]
        assert result["removed_count"] == 2
        assert "# Module comment" in modified
        assert "# inline comment" in modified
        assert "# Function below" in modified
        assert "def foo():" in modified

    def test_removal_skips_variables_without_values(self) -> None:
        """Test that variables without values are skipped."""
        source = "x: int = 42\ny: str\nz: float = 3.14\n"
        
        insertion_engine = InsertionEngine()

        # Try to remove all
        modified, result = insertion_engine.remove_types_bulk(source, None)
        
        assert result["success"]
        assert result["removed_count"] == 2  # Only x and z
        assert len(result["skipped"]) == 1
        assert "y" in result["skipped"]
        assert "y: str" in modified  # y preserved


class TestInsertRemoveRoundTrip:
    """Test round-trip operations between insertion and removal."""

    def test_insert_all_then_remove_all(self) -> None:
        """Test inserting all types then removing all returns to original."""
        original = "x = 42\nname = 'hello'\nitems = [1, 2, 3]\n"
        
        inference_engine = LiteralInferenceEngine()
        validator = TypeValidator()
        insertion_engine = InsertionEngine()

        # Step 1: Infer and insert all types
        types_map = inference_engine.infer_variable_types(original)
        scope = validator.extract_scope_names(original)
        validated_types = {
            var: type_str
            for var, type_str in types_map.items()
            if validator.validate(type_str, scope)
        }
        
        with_types, insert_result = insertion_engine.insert_types_bulk(
            original, validated_types
        )
        assert insert_result["success"]
        assert insert_result["inserted_count"] == 3

        # Step 2: Remove all types
        back_to_original, remove_result = insertion_engine.remove_types_bulk(
            with_types, None
        )
        assert remove_result["success"]
        assert remove_result["removed_count"] == 3

        # Should match original
        assert back_to_original == original

    def test_remove_all_then_insert_all(self) -> None:
        """Test removing all types then inserting them back."""
        original = "x: int = 42\nname: str = 'hello'\nitems: list = [1, 2, 3]\n"
        
        inference_engine = LiteralInferenceEngine()
        validator = TypeValidator()
        insertion_engine = InsertionEngine()

        # Step 1: Remove all types
        without_types, remove_result = insertion_engine.remove_types_bulk(original, None)
        assert remove_result["success"]
        assert remove_result["removed_count"] == 3

        # Step 2: Infer and insert types back
        types_map = inference_engine.infer_variable_types(without_types)
        scope = validator.extract_scope_names(without_types)
        validated_types = {
            var: type_str
            for var, type_str in types_map.items()
            if validator.validate(type_str, scope)
        }
        
        back_to_original, insert_result = insertion_engine.insert_types_bulk(
            without_types, validated_types
        )
        assert insert_result["success"]
        assert insert_result["inserted_count"] == 3

        # Should match original
        assert back_to_original == original

    def test_partial_insert_partial_remove(self) -> None:
        """Test inserting some types then removing different ones."""
        original = "x = 42\ny = 'hello'\nz = 3.14\n"
        
        inference_engine = LiteralInferenceEngine()
        validator = TypeValidator()
        insertion_engine = InsertionEngine()

        # Step 1: Insert types for x and y only
        types_map = inference_engine.infer_variable_types(original)
        scope = validator.extract_scope_names(original)
        
        partial_types = {"x": types_map["x"], "y": types_map["y"]}
        with_some_types, insert_result = insertion_engine.insert_types_bulk(
            original, partial_types
        )
        assert insert_result["success"]
        assert insert_result["inserted_count"] == 2

        # Step 2: Remove type from x only
        final, remove_result = insertion_engine.remove_types_bulk(
            with_some_types, ["x"]
        )
        assert remove_result["success"]
        assert remove_result["removed_count"] == 1

        # Final state: x and z without types, y with type
        assert "x = 42" in final
        assert "y: str = 'hello'" in final
        assert "z = 3.14" in final


class TestServerComponentIntegration:
    """Test that server components work together with removal functionality."""

    def test_can_import_server_with_removal_handlers(self) -> None:
        """Test that server module imports successfully with removal handlers."""
        try:
            from auto_type import server
            assert hasattr(server, 'server')
            assert hasattr(server, 'inference_engine')
            assert hasattr(server, 'type_validator')
            assert hasattr(server, 'insertion_engine')
        except Exception as e:
            pytest.fail(f"Failed to import server module: {e}")

    def test_server_has_removal_handlers(self) -> None:
        """Test that server has removal LSP handlers registered."""
        from auto_type import server
        
        # Check that removal handler functions exist
        assert callable(server.remove_types_in_file)
        assert callable(server.preview_removals)

    def test_removal_handler_workflow(self) -> None:
        """Test the workflow that removal handlers would use."""
        from auto_type.insertion import InsertionEngine
        from lsprotocol import types
        
        source = "x: int = 42\ny: str = 'hello'\n"
        
        # Test the workflow that remove_types_in_file would use
        insertion_engine = InsertionEngine()
        
        # Remove types
        modified_source, result = insertion_engine.remove_types_bulk(source, None)
        assert result["success"]
        assert result["removed_count"] == 2
        
        # Create WorkspaceEdit (this is what remove_types_in_file should return)
        text_edit = types.TextEdit(
            range=types.Range(
                start=types.Position(line=0, character=0),
                end=types.Position(line=len(source.splitlines()), character=0),
            ),
            new_text=modified_source,
        )
        
        workspace_edit = types.WorkspaceEdit(
            changes={"file:///test.py": [text_edit]}
        )
        
        # Verify the edit structure
        assert workspace_edit.changes is not None
        assert "file:///test.py" in workspace_edit.changes
        assert len(workspace_edit.changes["file:///test.py"]) == 1

    def test_preview_removal_workflow(self) -> None:
        """Test the preview workflow."""
        from auto_type.insertion import InsertionEngine
        
        source = "x: int = 42\ny: str = 'hello'\nz: float = 3.14\n"
        
        insertion_engine = InsertionEngine()
        
        # Preview removal of specific variables
        preview = insertion_engine.preview_removals(source, ["x", "z"])
        
        assert preview["success"]
        assert preview["total_changes"] == 2
        assert len(preview["will_remove"]) == 2
        
        # Verify preview structure
        for item in preview["will_remove"]:
            assert "variable" in item
            assert "type" in item
            assert "line" in item
        
        # y should not be in will_remove
        removed_vars = [item["variable"] for item in preview["will_remove"]]
        assert "x" in removed_vars
        assert "z" in removed_vars
        assert "y" not in removed_vars


class TestComplexScenarios:
    """Test complex real-world scenarios."""

    def test_large_file_with_mixed_annotations(self) -> None:
        """Test removal on a larger, more realistic file."""
        source = """# Configuration module
from typing import Optional

DEBUG: bool = True
API_KEY = "secret"
MAX_RETRIES: int = 3
timeout = 30
endpoints: list = ['api/v1', 'api/v2']

class Config:
    name = "default"
    
def get_config():
    return Config()

result = get_config()
"""
        
        insertion_engine = InsertionEngine()

        # Remove all variable-level type annotations
        modified, result = insertion_engine.remove_types_bulk(source, None)
        
        # Should remove DEBUG, MAX_RETRIES, and endpoints annotations
        assert result["success"]
        assert result["removed_count"] == 3
        
        # Verify specific removals
        assert "DEBUG = True" in modified
        assert "MAX_RETRIES = 3" in modified
        assert "endpoints = ['api/v1', 'api/v2']" in modified
        
        # Verify unannotated variables remain unchanged
        assert "API_KEY = \"secret\"" in modified
        assert "timeout = 30" in modified
        
        # Verify code structure preserved
        assert "from typing import Optional" in modified
        assert "class Config:" in modified
        assert "def get_config():" in modified

    def test_removal_with_complex_types(self) -> None:
        """Test removal of complex type annotations."""
        source = """data: dict[str, list[int]] = {"a": [1, 2]}
optional: int | None = None
generic: list[dict[str, Any]] = []
"""
        
        insertion_engine = InsertionEngine()

        # Remove all
        modified, result = insertion_engine.remove_types_bulk(source, None)
        
        assert result["success"]
        assert result["removed_count"] == 3
        assert 'data = {"a": [1, 2]}' in modified
        assert "optional = None" in modified
        assert "generic = []" in modified

    def test_selective_removal_with_not_found(self) -> None:
        """Test selective removal where some variables don't exist."""
        source = "x: int = 42\ny: str = 'hello'\n"
        
        insertion_engine = InsertionEngine()

        # Try to remove x, y, z, w (z and w don't exist)
        modified, result = insertion_engine.remove_types_bulk(
            source, ["x", "y", "z", "w"]
        )
        
        assert result["success"]
        assert result["removed_count"] == 2
        assert len(result["not_found"]) == 2
        assert "z" in result["not_found"]
        assert "w" in result["not_found"]
