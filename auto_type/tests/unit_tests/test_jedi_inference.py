"""Comprehensive tests for JediInferenceEngine.

Tests the Jedi-based type inference engine with focus on:
- Function return type inference (explicit and implicit)
- Variable type inference (annotated and inferred)
- Parameter type inference
- Expression type inference
- Integration with TypeEvalPy benchmark scenarios
- Error handling and edge cases
"""

import ast
import asyncio
from unittest.mock import MagicMock, patch

import pytest

from auto_type.inference.jedi_engine import JediInferenceEngine


@pytest.fixture
def engine():
    """Fixture to provide a JediInferenceEngine instance."""
    return JediInferenceEngine()


class TestFunctionReturnTypes:
    """Test function return type inference."""

    @pytest.mark.parametrize(
        "source,expected_type",
        [
            (
                """
def greet(name: str) -> str:
    return f"Hello, {name}"
""",
                "str",
            ),
            (
                """
def get_number():
    return 42
""",
                "int",
            ),
            (
                """
def get_message():
    return "hello"
""",
                "str",
            ),
            (
                """
def get_numbers():
    return [1, 2, 3]
""",
                "list",
            ),
            (
                """
def get_mapping():
    return {"a": 1, "b": 2}
""",
                "dict",
            ),
            (
                """
def get_coordinates():
    return 1, 2, 3
""",
                "tuple",
            ),
            (
                """
def get_unique():
    return {1, 2, 3, 2, 1}
""",
                "set",
            ),
            (
                """
def get_squares():
    return [x**2 for x in range(1, 6)]
""",
                "list",
            ),
            (
                """
def get_value() -> int:
    return "wrong_type"
""",
                "int",
            ),
        ],
    )
    async def test_return_inference(self, engine, source, expected_type):
        """Test various return type inference scenarios."""
        result = await engine.infer_types(source)
        func_scope = result.scope_tree.root.children[0]
        assert func_scope.return_type is not None
        if expected_type in ("list", "dict", "tuple", "set"):
            assert func_scope.return_type.type_str.startswith(expected_type)
        else:
            assert func_scope.return_type.type_str == expected_type

    async def test_return_custom_class(self, engine):
        """Test function returning custom class instance."""
        source = """
from collections import namedtuple

Point = namedtuple("Point", ["x", "y"])

def get_point():
    return Point(1, 2)
"""
        result = await engine.infer_types(source)

        func_scope = None
        for scope in result.scope_tree.root.children:
            if scope.name == "get_point":
                func_scope = scope
                break

        assert func_scope is not None
        assert func_scope.return_type is not None
        assert "Point" in func_scope.return_type.type_str

    async def test_return_union_types(self, engine):
        """Test function with multiple return types (union)."""
        source = """
def get_value(flag: bool):
    if flag:
        return 42
    else:
        return "hello"
"""
        result = await engine.infer_types(source)

        func_scope = result.scope_tree.root.children[0]
        assert func_scope.return_type is not None
        type_str = func_scope.return_type.type_str
        assert "int" in type_str and "str" in type_str

    async def test_return_none_explicit(self, engine):
        """Test function with explicit None return."""
        source = """
def do_nothing() -> None:
    print("doing nothing")
"""
        result = await engine.infer_types(source)

        func_scope = result.scope_tree.root.children[0]
        # NoneType might be inferred as None, NoneType, or Unknown depending on Jedi version
        assert func_scope.return_type is None or func_scope.return_type.type_str in (
            "None",
            "NoneType",
            "Unknown",
        )


class TestVariableTypeInference:
    """Test variable type inference."""

    @pytest.mark.parametrize(
        "source,var_name,expected_type",
        [
            ("x: int = 5", "x", "int"),
            ("x = 42", "x", "int"),
            ('x = "hello"', "x", "str"),
            ("x = [1, 2, 3]", "x", "list"),
            ('x = {"a": 1, "b": 2}', "x", "dict"),
            ("x = True", "x", "bool"),
            ("x = 3.14", "x", "float"),
        ],
    )
    async def test_variable_inference(self, engine, source, var_name, expected_type):
        """Test various variable type inference scenarios."""
        result = await engine.infer_types(source)
        assert var_name in result.scope_tree.root.variables
        type_str = result.scope_tree.root.variables[var_name].type_str
        if expected_type in ("list", "dict"):
            assert type_str.startswith(expected_type)
        else:
            assert type_str == expected_type

    async def test_function_call_return(self, engine):
        """Test variable assigned function call result."""
        source = """
def get_number() -> int:
    return 42

x = get_number()
"""
        result = await engine.infer_types(source)

        assert "x" in result.scope_tree.root.variables
        assert result.scope_tree.root.variables["x"].type_str == "int"

    async def test_variable_types_sync_api(self, engine):
        """Test infer_variable_types API."""
        source = "x = 42"
        types_map = await engine.infer_variable_types(source)
        assert types_map["x"] == "int"


class TestParameterTypeInference:
    """Test function parameter type inference."""

    async def test_annotated_parameter(self, engine):
        """Test parameter with explicit type annotation."""
        source = """
def greet(name: str):
    pass
"""
        result = await engine.infer_types(source)

        func_scope = result.scope_tree.root.children[0]
        assert "name" in func_scope.parameters
        assert func_scope.parameters["name"].type_str == "str"

    async def test_multiple_annotated_parameters(self, engine):
        """Test function with multiple annotated parameters."""
        source = """
def add(a: int, b: int) -> int:
    return a + b
"""
        result = await engine.infer_types(source)

        func_scope = result.scope_tree.root.children[0]
        assert "a" in func_scope.parameters
        assert "b" in func_scope.parameters
        assert func_scope.parameters["a"].type_str == "int"
        assert func_scope.parameters["b"].type_str == "int"

    async def test_mixed_parameter_annotations(self, engine):
        """Test function with mix of annotated and unannotated parameters."""
        source = """
def process(x: int, y):
    pass
"""
        result = await engine.infer_types(source)

        func_scope = result.scope_tree.root.children[0]
        assert "x" in func_scope.parameters
        assert func_scope.parameters["x"].type_str == "int"
        assert "y" in func_scope.parameters


class TestExpressionTypeInference:
    """Test expression type inference."""

    @pytest.mark.parametrize(
        "source,expression,expected_type",
        [
            ('names = ["Alice", "Bob"]', "names[0]", "str"),
            ('data = {"key": 42}', "data['key']", "int"),
            ("matrix = [[1, 2], [3, 4]]", "matrix[0][1]", "int"),
            (
                """
class Point:
    def __init__(self):
        self.x = 5
p = Point()
""",
                "p.x",
                "int",
            ),
            (
                """
def get_number() -> int:
    return 42
""",
                "get_number()",
                "int",
            ),
        ],
    )
    async def test_expression_inference(self, engine, source, expression, expected_type):
        """Test expression inference."""
        type_str = await engine.infer_expression_type(source, expression)
        assert type_str == expected_type

    async def test_expression_inference_failure(self, engine):
        """Test expression inference failure."""
        source = "x = 5"
        # Expression referring to non-existent variable
        type_str = await engine.infer_expression_type(source, "y")
        assert type_str is None

    async def test_expression_inference_synthetic_line_fail(self, engine):
        """Test failure when synthetic line cannot be found."""
        # This is hard to trigger with valid code, but we can check if it returns None for empty expression
        # or we can mock jedi
        type_str = await engine.infer_expression_type("x=1", "")
        assert type_str is None


class TestTypeEvalPyIntegration:
    """Test cases based on TypeEvalPy benchmark scenarios."""

    async def test_return_types_scenario(self, engine):
        """Test the return_types scenario from TypeEvalPy."""
        source = """
def func():
    return 1, 2, 3

a = func()

def func1():
    return {"a": 1, "b": 2, "c": 3}

b = func1()

def func4():
    return set([1, 2, 3, 2, 1])

d = func4()

def func5():
    return [x**2 for x in range(1, 6)]

e = func5()
"""
        result = await engine.infer_types(source)

        func_return_types = {}
        for scope in result.scope_tree.root.children:
            if scope.return_type:
                func_return_types[scope.name] = scope.return_type.type_str

        assert "func" in func_return_types
        assert func_return_types["func"].startswith("tuple")

        assert "func1" in func_return_types
        assert func_return_types["func1"].startswith("dict")

        assert "func4" in func_return_types
        assert func_return_types["func4"].startswith("set")

        assert "func5" in func_return_types
        assert func_return_types["func5"].startswith("list")

        assert "a" in result.scope_tree.root.variables
        assert result.scope_tree.root.variables["a"].type_str.startswith("tuple")

        assert "b" in result.scope_tree.root.variables
        assert result.scope_tree.root.variables["b"].type_str.startswith("dict")

        assert "d" in result.scope_tree.root.variables
        assert result.scope_tree.root.variables["d"].type_str.startswith("set")

        assert "e" in result.scope_tree.root.variables
        assert result.scope_tree.root.variables["e"].type_str.startswith("list")


class TestEdgeCases:
    """Test edge cases and error handling."""

    async def test_syntax_error_handling(self, engine):
        """Test that syntax errors are handled gracefully."""
        source = "def incomplete_func("
        result = await engine.infer_types(source)

        assert result.scope_tree.root is not None
        assert result.scope_tree.root.scope_type.value == "module"
        # Ensure it falls back gracefully
        assert len(result.scope_tree.root.children) == 0

    async def test_empty_source(self, engine):
        """Test inference on empty source code."""
        source = ""
        result = await engine.infer_types(source)

        assert result.scope_tree.root is not None

    async def test_function_without_return(self, engine):
        """Test function without explicit return statement."""
        source = """
def print_message(msg: str):
    print(msg)
"""
        result = await engine.infer_types(source)

        func_scope = result.scope_tree.root.children[0]
        assert func_scope.name == "print_message"

    async def test_ast_node_has_lineno_attribute(self, engine):
        """Test that manually created AST nodes have required position attributes."""
        source = """
def calculate(x, y):
    return x + y

class Calculator:
    def add(self, a, b):
        return a + b
"""
        result = await engine.infer_types(source)

        calc_scope = next(s for s in result.scope_tree.root.children if s.name == "calculate")
        assert isinstance(calc_scope.ast_node, ast.FunctionDef)
        assert hasattr(calc_scope.ast_node, "lineno")
        assert calc_scope.ast_node.lineno >= 1
        assert hasattr(calc_scope.ast_node, "col_offset")

        class_scope = next(s for s in result.scope_tree.root.children if s.name == "Calculator")
        assert isinstance(class_scope.ast_node, ast.ClassDef)
        assert hasattr(class_scope.ast_node, "lineno")
        assert class_scope.ast_node.lineno >= 1

    async def test_infer_types_at_locations(self, engine):
        """Test positional type inference."""
        source = "x = 10\ny = 'test'"
        locations = [(1, 0), (2, 0)]  # x and y
        results = await engine.infer_types_at_locations(source, locations)

        assert (1, 0) in results
        assert results[(1, 0)] == "int"
        assert (2, 0) in results
        assert results[(2, 0)] == "str"

    async def test_infer_types_at_locations_invalid(self, engine):
        """Test positional type inference with invalid locations."""
        source = "x = 10"
        locations = [(100, 0)]  # Invalid line
        results = await engine.infer_types_at_locations(source, locations)
        assert not results

    async def test_project_root_finding(self, engine, tmp_path):
        """Test finding project root via pyproject.toml."""
        project_dir = tmp_path / "my_project"
        project_dir.mkdir()
        (project_dir / "pyproject.toml").touch()
        source_file = project_dir / "src" / "main.py"
        source_file.parent.mkdir()
        source_file.touch()

        # We can't easily mock the internal _find_project_root call inside infer_types without patching,
        # but we can test the protected method directly if we want to ensure logic correctness.
        path, project = engine._find_project_root(str(source_file))
        assert path == str(source_file)
        assert project is not None
        assert str(project.path) == str(project_dir)

    async def test_project_root_finding_no_file(self, engine):
        """Test project root finding with non-existent file."""
        path, project = engine._find_project_root("/non/existent/path/file.py")
        assert path is None
        assert project is None

    async def test_project_root_finding_no_markers(self, engine, tmp_path):
        """Test project root finding when no markers exist."""
        # Create a file in a temp dir with no pyproject.toml
        source_file = tmp_path / "script.py"
        source_file.touch()

        path, project = engine._find_project_root(str(source_file))
        assert path == str(source_file)
        # Should return None when no project markers found
        assert project is None

    async def test_infer_types_concurrency(self, engine):
        """Test concurrent type inference requests."""
        source = "x = 42"
        # Simulate multiple concurrent requests
        tasks = [engine.infer_types(source) for _ in range(5)]
        results = await asyncio.gather(*tasks)
        assert len(results) == 5
        for result in results:
            assert "x" in result.scope_tree.root.variables

    @pytest.mark.parametrize(
        "original,expected",
        [
            ("List[int]", "list[int]"),
            ("Dict[str, Any]", "dict[str, Any]"),
            ("Union[str, None]", "str | None"),
            ("Optional[int]", "int | None"),
            ("Tuple[int, str]", "tuple[int, str]"),
            ("Set[int]", "set[int]"),
        ],
    )
    def test_normalize_type_name(self, engine, original, expected):
        """Test type name normalization for Python 3.12+."""
        assert engine._normalize_type_name(original) == expected

    async def test_project_root_finding_permission_error(self, engine, tmp_path):
        """Test handling of PermissionError during project root finding."""
        source_file = tmp_path / "script.py"
        source_file.touch()

        with patch("pathlib.Path.exists", side_effect=PermissionError("Permission denied")):
            path, project = engine._find_project_root(str(source_file))
            # Should fail gracefully, return None or fallback
            assert path is None or path == str(source_file)
            # If path returned, project might be None or fallback
            if project:
                assert str(project.path) == str(tmp_path) or str(project.path) == str(
                    source_file.parent
                )

    async def test_exception_in_infer_types_sync(self, engine):
        """Test exception handling in _infer_types_sync."""
        with patch("jedi.Script", side_effect=Exception("Jedi boom")):
            result = await engine.infer_types("x = 1")
            # Should return a safe fallback result
            assert result.scope_tree.root.name == "<module>"
            assert len(result.scope_tree.root.variables) == 0

    async def test_timeout_in_get_names(self, engine):
        """Test timeout handling in _get_names_with_timeout."""
        # Create a mock script that sleeps in get_names
        mock_script = MagicMock()

        def slow_get_names(*args, **kwargs):
            import time

            time.sleep(1)
            return []

        mock_script.get_names.side_effect = slow_get_names

        # We need to call _get_names_with_timeout directly with a short timeout
        result = engine._get_names_with_timeout(mock_script, timeout=0.1)
        assert result == []


class TestUnionTypeInference:
    """Test union type inference for improved type safety."""

    @pytest.mark.parametrize(
        "source,var_name,line,check_func",
        [
            (
                """
class Operation:
    def __init__(self):
        self.result = None
    def compute(self):
        self.result = 5
        return self.result
op = Operation()
res = op.compute()
""",
                "res",
                10,
                lambda t: "int" in t or "Unknown" in t,
            ),
            (
                """
def func(x):
    if x > 0: return 42
    else: return "neg"
val = int(input()) # Unknown value at static time
res = func(val)
""",
                "res",
                6,
                lambda t: "int" in t and "str" in t,
            ),
        ],
    )
    async def test_union_inference_scenarios(self, engine, source, var_name, line, check_func):
        result = await engine.infer_types(source)
        # Helper to find var type
        # Since we don't have get_variable_type_at_line exposed easily in the result (it's in ScopeTree but that takes line/col)
        # We can just look at module vars for simple cases
        # But wait, scope_tree.root.get_variable_type_at_line IS available
        type_info = result.scope_tree.root.get_variable_type_at_line(var_name, line)
        # If not found at line, check root variables
        if not type_info and var_name in result.scope_tree.root.variables:
            type_info = result.scope_tree.root.variables[var_name]

        assert type_info is not None
        assert check_func(type_info.type_str)

    async def test_function_reference_returns_callable(self, engine):
        """Test that function references are normalized to 'callable'."""
        source = """
def param_func():
    return "Hello"
b = param_func
"""
        result = await engine.infer_types(source)
        type_info = result.scope_tree.root.variables.get("b")
        assert type_info is not None
        assert type_info.type_str == "callable"

    async def test_itertools_inference(self, engine):
        """Test inference of itertools objects."""
        source = """
import itertools
c = itertools.cycle([1, 2])
"""
        result = await engine.infer_types(source)
        type_info = result.scope_tree.root.variables.get("c")
        assert type_info is not None
        assert "itertools.cycle" in type_info.type_str
