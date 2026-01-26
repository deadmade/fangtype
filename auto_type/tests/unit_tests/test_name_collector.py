"""Tests for the AST Name Collector."""

from auto_type.analysis.name_collector import NameCollector, NameLocation


class TestNameLocation:
    """Tests for the NameLocation dataclass."""

    def test_name_location_creation(self) -> None:
        """Test creating a NameLocation instance."""
        loc = NameLocation(name="x", line=1, col=0, is_definition=True, end_col=1)
        assert loc.name == "x"
        assert loc.line == 1
        assert loc.col == 0
        assert loc.is_definition is True
        assert loc.end_col == 1


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
        # Note: def inner(): is a FunctionDef node, not a Name node
        # So we only collect the call usage, not the definition
        assert len(inner_locs) == 1  # 1 usage (call)
