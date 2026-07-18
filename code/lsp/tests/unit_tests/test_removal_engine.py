from fangtype.removal import RemovalEngine


def test_remove_simple_variable_annotation():
    source = "x: int = 1\n"
    modified, result = RemovalEngine().remove_types(source, variables=["x"])

    assert modified.strip() == "x = 1"
    assert result["removed_count"] == 1
    assert result["success"] is True
    removal = next(entry for entry in result["will_remove"] if entry["variable"] == "x")
    assert removal["target_kind"] == "variable"


def test_remove_variable_without_value_is_skipped():
    source = "x: int\n"
    modified, result = RemovalEngine().remove_types(source, variables=["x"])

    assert modified.strip() == "x: int"
    assert result["removed_count"] == 0
    assert result["success"] is False
    assert result["will_skip"]
    # L22: a skipped target was found -- it must not also be reported as not_found.
    assert result["not_found"] == []


def test_remove_function_annotations_when_allowed():
    source = "def greet(name: str) -> str:\n    return name\n"
    modified, result = RemovalEngine().remove_types(source, variables=None, include_functions=True)

    assert "name: str" not in modified
    assert "-> str" not in modified
    removed_count = result["removed_count"]
    assert isinstance(removed_count, int)
    assert removed_count >= 2
    removal_kinds = {entry["variable"]: entry["target_kind"] for entry in result["will_remove"]}
    assert removal_kinds.get("greet.name") == "function_param"
    assert removal_kinds.get("greet.return") == "function_return"


def test_remove_types_only_touches_the_requested_line():
    source = 'def a():\n    count: int = 0\n\n\ndef b():\n    count: str = ""\n'
    modified, result = RemovalEngine().remove_types(source, variables=["count"], line=2)

    assert result["removed_count"] == 1
    assert "count = 0" in modified
    assert 'count: str = ""' in modified


def test_remove_types_with_empty_variables_removes_nothing():
    source = "x: int = 1\n"
    modified, result = RemovalEngine().remove_types(source, variables=[])

    assert modified == source
    assert result["removed_count"] == 0


def test_preview_removals_reports_counts():
    source = "x: int = 5\n"
    preview = RemovalEngine().preview_removals(source, variables=["x"])

    assert preview["total_changes"] == preview["removed_count"]
    assert preview["will_remove"]
