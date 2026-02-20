from auto_type.insertion.removal_engine import TypeRemovalEngine


def test_remove_simple_variable_annotation():
    source = "x: int = 1\n"
    modified, result = TypeRemovalEngine.remove_types(source, variables=["x"])

    assert modified.strip() == "x = 1"
    assert result["removed_count"] == 1
    assert result["success"] is True
    assert any(entry["variable"] == "x" for entry in result["will_remove"])


def test_remove_variable_without_value_is_skipped():
    source = "x: int\n"
    modified, result = TypeRemovalEngine.remove_types(source, variables=["x"])

    assert modified.strip() == "x: int"
    assert result["removed_count"] == 0
    assert result["success"] is False
    assert result["will_skip"]


def test_remove_function_annotations_when_allowed():
    source = "def greet(name: str) -> str:\n    return name\n"
    modified, result = TypeRemovalEngine.remove_types(
        source, variables=None, include_functions=True
    )

    assert "name: str" not in modified
    assert "-> str" not in modified
    assert result["removed_count"] >= 2
    keys = {entry["variable"] for entry in result["will_remove"]}
    assert "greet.name" in keys or "greet.return" in keys


def test_preview_removals_reports_counts():
    source = "x: int = 5\n"
    preview = TypeRemovalEngine.preview_removals(source, variables=["x"])

    assert preview["total_changes"] == preview["removed_count"]
    assert preview["will_remove"]
