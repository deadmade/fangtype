"""Tests for the AST Name Collector."""

from fangtype.analysis.name_collector import NameCollector


class TestNameCollector:
    """Tests for the NameCollector class."""

    def test_collects_variable_definition(self) -> None:
        """Test collecting a simple variable definition."""
        source = "x = 42"
        locations = NameCollector.collect_from_source(source)

        assert len(locations) == 1
        assert locations[0].name == "x"
        assert locations[0].is_definition is True
        assert locations[0].line == 1
        assert locations[0].col == 0
        assert locations[0].end_col == 1

    def test_collects_variable_usage(self) -> None:
        """Test collecting a variable usage."""
        source = """x = 42
y = x + 1"""
        locations = NameCollector.collect_from_source(source)

        # Should have: x (definition), y (definition), x (usage)
        assert len(locations) == 3

        x_usage = [loc for loc in locations if loc.name == "x" and not loc.is_definition]
        assert len(x_usage) == 1
        assert x_usage[0].line == 2
        assert x_usage[0].col == 4

    def test_collects_multiple_usages(self) -> None:
        """Test collecting multiple usages of the same variable."""
        source = """x = 42
print(x)
y = x + x"""
        locations = NameCollector.collect_from_source(source)

        x_usages = [loc for loc in locations if loc.name == "x" and not loc.is_definition]
        assert len(x_usages) == 3  # print(x), x + x (two uses)

    def test_collects_function_call(self) -> None:
        """Test collecting a function name usage."""
        source = """def foo():
    pass

foo()"""
        locations = NameCollector.collect_from_source(source)

        foo_usages = [loc for loc in locations if loc.name == "foo" and not loc.is_definition]
        assert len(foo_usages) == 1
        assert foo_usages[0].line == 4

    def test_collects_usages_only(self) -> None:
        """Test the collect_usages_only method."""
        source = """x = 42
y = x + 1
z = y + x"""
        usages = NameCollector.collect_usages_only(source)

        # Should only have usages, no definitions
        for loc in usages:
            assert loc.is_definition is False

        names = [loc.name for loc in usages]
        assert names.count("x") == 2
        assert names.count("y") == 1

    def test_collect_in_range(self) -> None:
        """Test collecting usages within a line range."""
        source = """line1 = 1
line2 = line1
line3 = line2
line4 = line3
line5 = line4"""
        # Collect usages in lines 2-3 (0-based) with buffer=0
        usages = NameCollector.collect_in_range(source, start_line=1, end_line=2, buffer=0)

        # Should get usages from lines 2 and 3 (1-based lines 2 and 3)
        lines = [loc.line for loc in usages]
        assert all(2 <= line <= 3 for line in lines)

    def test_handles_syntax_error(self) -> None:
        """Test that syntax errors return empty list."""
        source = "def broken("
        locations = NameCollector.collect_from_source(source)
        assert locations == []

    def test_empty_source(self) -> None:
        """Test collecting from empty source."""
        source = ""
        locations = NameCollector.collect_from_source(source)
        assert locations == []

    def test_complex_expressions(self) -> None:
        """Test collecting names from complex expressions."""
        source = """data = [1, 2, 3]
result = sum(data) + len(data)"""
        locations = NameCollector.collect_from_source(source)

        # Should include: data (def), result (def), sum (use), data (use), len (use), data (use)
        data_locs = [loc for loc in locations if loc.name == "data"]
        assert len(data_locs) == 3  # 1 definition + 2 usages

    def test_nested_scopes(self) -> None:
        """Test collecting names from nested function scopes."""
        source = """def outer():
    x = 1
    def inner():
        return x
    return inner()"""
        locations = NameCollector.collect_from_source(source)

        x_locs = [loc for loc in locations if loc.name == "x"]
        assert len(x_locs) == 2  # 1 definition + 1 usage

        inner_locs = [loc for loc in locations if loc.name == "inner"]
        # def inner() is a FunctionDef node, not a Name, so only the call usage is collected
        assert len(inner_locs) == 1  # 1 usage (call)


class TestExpressionCollection:
    """Tests for subscript/attribute expression collection (include_expressions)."""

    def test_expressions_absent_by_default(self) -> None:
        """Without include_expressions, subscript/attribute expressions are not collected."""
        source = "y = bar[0]\nz = obj.attr\n"
        locations = NameCollector.collect_in_range(source, 0, 2)

        names = {loc.name for loc in locations}
        assert "bar[0]" not in names
        assert "obj.attr" not in names
        # bare base names are still present as usages
        assert "bar" in names
        assert "obj" in names

    def test_subscript_and_attribute_expressions_collected(self) -> None:
        """With include_expressions, whole subscript/attribute expressions are emitted."""
        source = "y = bar[0]\nz = obj.attr\n"
        locations = NameCollector.collect_in_range(source, 0, 2, include_expressions=True)

        by_name = {loc.name: loc for loc in locations}
        assert "bar[0]" in by_name
        assert "obj.attr" in by_name
        # positioned at the start of the expression, marked as usage
        assert by_name["bar[0]"].col == 4
        assert by_name["bar[0]"].is_definition is False

    def test_store_context_expression_is_definition(self) -> None:
        """Assignment target subscript/attribute is a definition, filtered out of usages."""
        source = "d[key] = 1\n"
        locations = NameCollector.collect_in_range(source, 0, 1, include_expressions=True)

        # d[key] is a Store target -> is_definition -> filtered out of usage collection
        assert "d[key]" not in {loc.name for loc in locations}


class TestParameterCollection:
    """Tests for parameter-name collection (include_parameters flag)."""

    def test_parameters_absent_by_default(self) -> None:
        """Without include_parameters, parameters are not emitted, so callers are unaffected."""
        source = "def f(a, b):\n    pass\n"
        names = {loc.name for loc in NameCollector.collect_from_source(source)}
        assert "a" not in names
        assert "b" not in names

    def test_parameters_emitted_when_enabled(self) -> None:
        """With include_parameters, each parameter is emitted as a definition."""
        source = "def f(a, b, *args, **kwargs):\n    pass\n"
        collector = NameCollector(include_parameters=True)
        collector.visit(__import__("ast").parse(source))
        by_name = {loc.name: loc for loc in collector.names}

        for pname, col in (("a", 6), ("b", 9)):
            assert pname in by_name
            assert by_name[pname].is_definition is True
            assert by_name[pname].line == 1
            assert by_name[pname].col == col
            assert by_name[pname].end_col == col + len(pname)
        # *args / **kwargs bind the bare names too
        assert "args" in by_name
        assert "kwargs" in by_name

    def test_parameters_excluded_from_usages_only(self) -> None:
        """Parameters are definitions, so collect_usages_only never yields them."""
        source = "def f(a, b):\n    return a + b\n"
        usages = NameCollector.collect_usages_only(source)
        usage_names = [loc.name for loc in usages]
        # the two body usages remain; the signature bindings are not usages
        assert usage_names.count("a") == 1
        assert usage_names.count("b") == 1


class TestNameAtPosition:
    """Tests for the cursor -> NameLocation resolver (Jedi-free goto replacement)."""

    def test_variable_definition(self) -> None:
        loc = NameCollector.name_at_position("x = 42", 1, 0)
        assert loc is not None
        assert loc.name == "x"
        assert loc.is_definition is True

    def test_variable_usage(self) -> None:
        source = "x = 42\ny = x + 1"
        loc = NameCollector.name_at_position(source, 2, 4)
        assert loc is not None
        assert loc.name == "x"
        assert loc.is_definition is False

    def test_parameter_in_signature(self) -> None:
        loc = NameCollector.name_at_position("def f(a, b):\n    pass\n", 1, 6)
        assert loc is not None
        assert loc.name == "a"
        assert loc.is_definition is True
        assert loc.line == 1

    def test_attribute_cursor_on_attr(self) -> None:
        source = "class C:\n    def __init__(self):\n        self.width = 5\n"
        loc = NameCollector.name_at_position(source, 3, 15)  # on "width"
        assert loc is not None
        assert loc.name == "self.width"
        assert loc.is_definition is True

    def test_attribute_cursor_on_self_prefers_definition(self) -> None:
        source = "class C:\n    def __init__(self):\n        self.width = 5\n"
        loc = NameCollector.name_at_position(source, 3, 9)  # on "self"
        assert loc is not None
        assert loc.name == "self.width"  # Store attribute expr beats the self usage

    def test_subscript_store(self) -> None:
        loc = NameCollector.name_at_position("d[k] = 1", 1, 0)  # on "d"
        assert loc is not None
        assert loc.name == "d[k]"
        assert loc.is_definition is True

    def test_subscript_load_picks_target(self) -> None:
        loc = NameCollector.name_at_position("value = d['k']", 1, 0)
        assert loc is not None
        assert loc.name == "value"

    def test_cursor_on_whitespace(self) -> None:
        assert NameCollector.name_at_position("x = 42", 1, 3) is None

    def test_cursor_at_end_col_boundary_is_exclusive(self) -> None:
        # "x" occupies col 0 only; col 1 (== end_col) is not covered
        assert NameCollector.name_at_position("x = 42", 1, 1) is None

    def test_cursor_on_function_def_name(self) -> None:
        assert NameCollector.name_at_position("def foo():\n    pass\n", 1, 4) is None

    def test_cursor_on_class_def_name(self) -> None:
        assert NameCollector.name_at_position("class Foo:\n    pass\n", 1, 6) is None

    def test_syntax_error_returns_none(self) -> None:
        assert NameCollector.name_at_position("def broken(", 1, 0) is None


class TestNonAsciiColumns:
    """Regression tests for UTF-16/byte/code-point column conflation in NameLocation."""

    def test_columns_are_code_points_not_bytes(self) -> None:
        # 'café_x' starts at code-point/UTF-16 col 8; its byte offset is 9 ('é'=2 bytes).
        source = "café_y = café_x"
        locs = NameCollector.collect_from_source(source)
        by_name = {loc.name: loc for loc in locs}
        assert by_name["café_y"].col == 0
        assert by_name["café_y"].end_col == 6  # 6 code points in "café_y"
        # Usage "café_x" is after "café_y = " -> code-point col 9, NOT byte col 10.
        assert by_name["café_x"].col == 9
        assert by_name["café_x"].end_col == 15

    def test_selects_right_variable_after_accent(self) -> None:
        # Multi-byte char precedes 'y'; its UTF-16 cursor col is 9 ("café_x = " is 9 units).
        source = "café_x = y"
        # 'y' is at UTF-16/code-point col 9 (é is 1 UTF-16 unit).
        loc = NameCollector.name_at_position(source, 1, 9)
        assert loc is not None
        assert loc.name == "y"

    def test_bmp_accent_cursor_on_target(self) -> None:
        # Cursor on 'x' in "α = x" (α is 1 UTF-16 unit, 2 UTF-8 bytes).
        source = "α = x"
        loc = NameCollector.name_at_position(source, 1, 4)  # 'x'
        assert loc is not None
        assert loc.name == "x"

    def test_astral_char_in_string_shifts_utf16_cursor(self) -> None:
        # Astral char 😀 (2 UTF-16 units, 1 code point) shifts 'target' UTF-16 cursor to 10 vs 9.
        source = 's = "😀"; target = s'
        loc = NameCollector.name_at_position(source, 1, 10)
        assert loc is not None
        assert loc.name == "target"
