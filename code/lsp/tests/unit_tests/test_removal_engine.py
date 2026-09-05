from fangtype.removal import RemovalEngine


def test_remove_simple_variable_annotation():
    source = "x: int = 1\n"
    modified, result = RemovalEngine().remove_types(source, variables=["x"])

    assert modified.strip() == "x = 1"
    assert result["removed_count"] == 1
    assert result["success"] is True
    removal = next(entry for entry in result["will_remove"] if entry["variable"] == "x")
    assert removal["target_kind"] == "variable"


def test_remove_standalone_declaration_deletes_the_statement():
    """A bare `x: int` is the shape the insertion path writes for a binding PEP 526 cannot
    annotate in place, so removal has to take it back or the tool's own output is one-way.

    There is no assignment to keep, so the inverse of writing the line is deleting it.
    """
    source = "x: int\n"
    modified, result = RemovalEngine().remove_types(source, variables=["x"])

    assert modified.strip() == ""
    assert result["removed_count"] == 1
    assert result["success"] is True
    assert result["will_skip"] == []
    assert result["not_found"] == []


def test_removing_a_declaration_leaves_the_surrounding_statements():
    source = "def f(seq):\n    total: int\n    for total in seq:\n        pass\n"
    modified, result = RemovalEngine().remove_types(source, variables=["total"])

    assert modified == "def f(seq):\n    for total in seq:\n        pass\n"
    assert result["removed_count"] == 1


def test_class_level_declaration_is_still_skipped():
    """At class scope a bare declaration is a field, not just a type claim. Deleting one drops
    a dataclass or TypedDict member, which is more than removing an annotation.
    """
    source = "import dataclasses\n\n\n@dataclasses.dataclass\nclass Point:\n    x: int\n"
    modified, result = RemovalEngine().remove_types(source, variables=["x"])

    assert "x: int" in modified
    assert result["removed_count"] == 0
    assert result["will_skip"]
    # L22: a skipped target was found -- it must not also be reported as not_found.
    assert result["not_found"] == []


def test_declaration_inside_a_method_is_not_treated_as_a_field():
    source = "class A:\n    def f(self, seq):\n        total: int\n        for total in seq:\n            pass\n"
    modified, result = RemovalEngine().remove_types(source, variables=["total"])

    assert "total: int" not in modified
    assert result["removed_count"] == 1


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


def test_preview_removals_includes_functions_when_allowed():
    source = "def greet(name: str) -> str:\n    return name\n"
    skipped = RemovalEngine().preview_removals(source, include_functions=False)
    included = RemovalEngine().preview_removals(source, include_functions=True)

    assert skipped["total_changes"] == 0
    included_total = included["total_changes"]
    assert isinstance(included_total, int)
    assert included_total >= 2
