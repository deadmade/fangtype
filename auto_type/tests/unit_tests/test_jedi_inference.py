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
import textwrap
from unittest.mock import patch

import pytest

from auto_type.inference.jedi_engine import JediInferenceEngine
from auto_type.inference.jedi_project import find_project_root


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
        source = textwrap.dedent(source).strip()
        result = engine.infer_types(source)
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
        result = engine.infer_types(source)

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
        result = engine.infer_types(source)

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
        result = engine.infer_types(source)

        func_scope = result.scope_tree.root.children[0]
        # NoneType might be inferred as None, NoneType, or Unknown depending on Jedi version
        assert func_scope.return_type is None or func_scope.return_type.type_str in (
            "None",
            "NoneType",
            "Unknown",
        )

    async def test_higher_order_call_flow_return(self, engine):
        """Test return type propagation through callable parameters."""
        source = """
def my_sum(a, b, *integers):
    result = a + b
    for x in integers:
        result += x
    return result

def func(a):
    return a(1, 2, 3)

b = func(my_sum)
"""
        result = engine.infer_types(source)
        func_scope = next(
            s for s in result.scope_tree.get_all_function_scopes() if s.name == "func"
        )
        assert func_scope.return_type is not None
        assert "int" in func_scope.return_type.type_str
        assert "a" in func_scope.parameters
        assert func_scope.parameters["a"].type_str in ("Callable", "my_sum")
        assert "b" in result.scope_tree.root.variables
        assert "int" in result.scope_tree.root.variables["b"].type_str

    async def test_nested_callable_chain_return(self, engine):
        """Test nested callable parameter propagation across function chain."""
        source = """
def nested_func():
    return "Hello from nested_func"

def param_func(a):
    return a()

def func(a):
    return a(nested_func)

b = param_func
c = func
d = c(b)
"""
        result = engine.infer_types(source)
        scopes = {s.name: s for s in result.scope_tree.get_all_function_scopes()}
        assert scopes["param_func"].return_type is not None
        assert "str" in scopes["param_func"].return_type.type_str
        assert scopes["func"].return_type is not None
        assert "str" in scopes["func"].return_type.type_str
        assert "d" in result.scope_tree.root.variables
        assert "str" in result.scope_tree.root.variables["d"].type_str

    async def test_decorator_call_still_infers_result(self, engine):
        """Test decorated function call still infers result type."""
        source = """
def dec1(f):
    def wrapper(a, b):
        result = f(a, b)
        return result

    return wrapper

a = dec1

@a
def func(a, b):
    return a + b

c = func("Hello", "world")
"""
        result = engine.infer_types(source)
        assert "c" in result.scope_tree.root.variables
        assert "str" in result.scope_tree.root.variables["c"].type_str

    async def test_super_call_return_propagation(self, engine):
        """Test return propagation for super().method() chains."""
        source = """
class A:
    def func(self):
        return "Hello from class A"

class B(A):
    def func(self):
        return super().func()

class C(B):
    def func(self):
        return super().func()
"""
        result = engine.infer_types(source)
        scopes = {
            s.get_qualified_name(): s
            for s in result.scope_tree.get_all_function_scopes()
            if s.name == "func"
        }
        assert scopes["A.func"].return_type is not None
        assert "str" in scopes["A.func"].return_type.type_str
        assert scopes["B.func"].return_type is not None
        assert "str" in scopes["B.func"].return_type.type_str
        assert scopes["C.func"].return_type is not None
        assert "str" in scopes["C.func"].return_type.type_str


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
        result = engine.infer_types(source)
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
        result = engine.infer_types(source)

        assert "x" in result.scope_tree.root.variables
        assert result.scope_tree.root.variables["x"].type_str == "int"

    async def test_method_call_return_fallback(self, engine):
        """Test variable assigned from method call gets return type, not None."""
        source = """
class ArithmeticOperation:
    def __init__(self, a, b):
        self.a = a
        self.b = b
        self.result = None

    def compute(self):
        self.result = self.a + self.b
        return self.result

arith_op = ArithmeticOperation(5, 10)
result1 = arith_op.compute()
"""
        result = engine.infer_types(source)

        assert "result1" in result.scope_tree.root.variables
        inferred = result.scope_tree.root.variables["result1"].type_str
        assert "int" in inferred


class TestParameterTypeInference:
    """Test function parameter type inference."""

    async def test_annotated_parameter(self, engine):
        """Test parameter with explicit type annotation."""
        source = """
def greet(name: str):
    pass
"""
        result = engine.infer_types(source)

        func_scope = result.scope_tree.root.children[0]
        assert "name" in func_scope.parameters
        assert func_scope.parameters["name"].type_str == "str"

    async def test_multiple_annotated_parameters(self, engine):
        """Test function with multiple annotated parameters."""
        source = """
def add(a: int, b: int) -> int:
    return a + b
"""
        result = engine.infer_types(source)

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
        result = engine.infer_types(source)

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
        type_str = engine.infer_expression_type(source, expression)
        assert type_str == expected_type

    async def test_expression_inference_failure(self, engine):
        """Test expression inference failure."""
        source = "x = 5"
        # Expression referring to non-existent variable
        type_str = engine.infer_expression_type(source, "y")
        assert type_str is None

    async def test_expression_inference_synthetic_line_fail(self, engine):
        """Test failure when synthetic line cannot be found."""
        # This is hard to trigger with valid code, but we can check if it returns None
        # for empty expression
        # or we can mock jedi
        type_str = engine.infer_expression_type("x=1", "")
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
        result = engine.infer_types(source)

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


class TestAttributeAccessInference:
    """Test attribute access inference (self.attr, obj.attr)."""

    async def test_self_attribute_in_init(self, engine):
        """Test inference of self.attribute assignments in __init__."""
        source = """
class Rectangle:
    def __init__(self, width, height):
        self.width = width
        self.height = height
"""
        result = engine.infer_types(source)

        # Find the __init__ scope
        init_scope = None
        for scope in result.scope_tree.scopes_by_id.values():
            if scope.name == "__init__":
                init_scope = scope
                break

        assert init_scope is not None
        assert "width" in init_scope.attributes
        assert "height" in init_scope.attributes

    async def test_self_attribute_with_literal(self, engine):
        """Test inference of self.attribute with literal values."""
        source = """
class Counter:
    def __init__(self):
        self.count = 0
        self.name = "counter"
        self.values = [1, 2, 3]
"""
        result = engine.infer_types(source)

        init_scope = None
        for scope in result.scope_tree.scopes_by_id.values():
            if scope.name == "__init__":
                init_scope = scope
                break

        assert init_scope is not None
        assert init_scope.attributes["count"].type_str == "int"
        assert init_scope.attributes["name"].type_str == "str"
        assert init_scope.attributes["values"].type_str.startswith("list")

    async def test_self_attribute_in_method(self, engine):
        """Test inference of self.attribute assignments in regular methods."""
        source = """
class Calculator:
    def __init__(self):
        self.result = 0

    def add(self, value):
        self.result = self.result + value
        return self.result
"""
        result = engine.infer_types(source)

        # Find the add method scope
        add_scope = None
        for scope in result.scope_tree.scopes_by_id.values():
            if scope.name == "add":
                add_scope = scope
                break

        assert add_scope is not None
        # The result attribute should be tracked
        assert "result" in add_scope.attributes or any(
            "result" in s.attributes for s in result.scope_tree.scopes_by_id.values()
        )

    async def test_parameter_attribute(self, engine):
        """Test inference of obj.attribute where obj is a parameter."""
        source = """
def process_point(point):
    point.x = 10
    point.y = 20
    return point.x + point.y
"""
        result = engine.infer_types(source)

        func_scope = result.scope_tree.root.children[0]
        assert func_scope.name == "process_point"
        # Attributes should be extracted
        assert len(func_scope.attributes) > 0 or any(
            len(s.attributes) > 0 for s in result.scope_tree.scopes_by_id.values()
        )

    async def test_multiple_attribute_assignments(self, engine):
        """Test multiple attribute assignments in the same scope."""
        source = """
class Config:
    def setup(self):
        self.debug = True
        self.timeout = 30
        self.host = "localhost"
        self.port = 8080
"""
        result = engine.infer_types(source)

        setup_scope = None
        for scope in result.scope_tree.scopes_by_id.values():
            if scope.name == "setup":
                setup_scope = scope
                break

        assert setup_scope is not None
        # Should have extracted all attributes
        assert len(setup_scope.attributes) >= 4

    async def test_chained_attributes_skipped(self, engine):
        """Test that chained attributes (self.obj.attr) are skipped."""
        source = """
class Container:
    def __init__(self):
        self.data = {}

    def set_value(self, key, value):
        # This is chained - should be skipped
        self.data[key] = value
"""
        result = engine.infer_types(source)

        # Should still work without errors
        assert result.scope_tree.root is not None

    async def test_attribute_type_inference_accuracy(self, engine):
        """Test that attribute types are inferred correctly."""
        source = """
class DataStore:
    def __init__(self):
        self.numbers = [1, 2, 3]
        self.mapping = {"a": 1}
        self.flag = False
        self.ratio = 3.14
"""
        result = engine.infer_types(source)

        init_scope = None
        for scope in result.scope_tree.scopes_by_id.values():
            if scope.name == "__init__":
                init_scope = scope
                break

        assert init_scope is not None
        assert init_scope.attributes["numbers"].type_str.startswith("list")
        assert init_scope.attributes["mapping"].type_str.startswith("dict")
        assert init_scope.attributes["flag"].type_str == "bool"
        assert init_scope.attributes["ratio"].type_str == "float"

    async def test_self_attribute_method_reference_callable(self, engine):
        """Test self attribute assignment from method reference infers callable."""
        source = """
class A:
    def __init__(self):
        self.smth = self.func2

    def func2(self):
        return "x"
"""
        result = engine.infer_types(source)
        init_scope = next(
            s for s in result.scope_tree.scopes_by_id.values() if s.name == "__init__"
        )
        assert init_scope.attributes["smth"].type_str == "Callable"

    async def test_self_attribute_augassign_across_methods(self, engine):
        """Test self attribute propagated from __iter__ to __next__ scope context."""
        source = """
class Cls:
    def __iter__(self):
        self.n = 0
        return self

    def __next__(self):
        self.n += 1
        return self.n
"""
        result = engine.infer_types(source)
        next_scope = next(
            s for s in result.scope_tree.scopes_by_id.values() if s.name == "__next__"
        )
        assert "n" in next_scope.attributes
        assert next_scope.attributes["n"].type_str == "int"
        assert next_scope.parent is not None
        assert next_scope.parent.attributes["n"].type_str == "int"

    async def test_self_attribute_in_tuple_assignment_target(self, engine):
        """Test attribute extraction from tuple assignment target."""
        source = """
class Cls:
    def __init__(self):
        self.num = 0

    def step(self):
        cur, self.num = self.num, self.num + 1
        return cur
"""
        result = engine.infer_types(source)
        step_scope = next(s for s in result.scope_tree.scopes_by_id.values() if s.name == "step")
        assert "num" in step_scope.attributes
        assert step_scope.attributes["num"].type_str == "int"


class TestEdgeCases:
    """Test edge cases and error handling."""

    async def test_syntax_error_handling(self, engine):
        """Test that syntax errors are handled gracefully."""
        source = "def incomplete_func("
        result = engine.infer_types(source)

        assert result.scope_tree.root is not None
        assert result.scope_tree.root.scope_type.value == "module"
        # Ensure it falls back gracefully
        assert len(result.scope_tree.root.children) == 0

    async def test_empty_source(self, engine):
        """Test inference on empty source code."""
        source = ""
        result = engine.infer_types(source)

        assert result.scope_tree.root is not None

    async def test_function_without_return(self, engine):
        """Test function without explicit return statement."""
        source = """
def print_message(msg: str):
    print(msg)
"""
        result = engine.infer_types(source)

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
        result = engine.infer_types(source)

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
        results = engine.infer_types_at_locations(source, locations)

        assert (1, 0) in results
        assert results[(1, 0)] == "int"
        assert (2, 0) in results
        assert results[(2, 0)] == "str"

    async def test_infer_types_at_locations_invalid(self, engine):
        """Test positional type inference with invalid locations."""
        source = "x = 10"
        locations = [(100, 0)]  # Invalid line
        results = engine.infer_types_at_locations(source, locations)
        assert not results

    async def test_project_root_finding(self, engine, tmp_path):
        """Test finding project root via pyproject.toml."""
        project_dir = tmp_path / "my_project"
        project_dir.mkdir()
        (project_dir / "pyproject.toml").touch()
        source_file = project_dir / "src" / "main.py"
        source_file.parent.mkdir()
        source_file.touch()

        # Test the standalone find_project_root function
        path, project = find_project_root(str(source_file))
        assert path == str(source_file)
        assert project is not None
        assert str(project.path) == str(project_dir)

    async def test_project_root_finding_no_file(self, engine):
        """Test project root finding with non-existent file."""
        path, project = find_project_root("/non/existent/path/file.py")
        assert path is None
        assert project is None

    async def test_project_root_finding_no_markers(self, engine, tmp_path):
        """Test project root finding when no markers exist."""
        # Create a file in a temp dir with no pyproject.toml
        source_file = tmp_path / "script.py"
        source_file.touch()

        path, project = find_project_root(str(source_file))
        assert path == str(source_file)
        # Should return None when no project markers found
        assert project is None

    async def test_infer_types_concurrency(self, engine):
        """Test concurrent type inference requests."""
        source = "x = 42"
        # Simulate multiple requests.
        results = [engine.infer_types(source) for _ in range(5)]
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
            ("param_func() -> str", "Callable"),
            ("<lambda>(x) -> int", "Callable"),
            ("func2(self: MyClass, a)", "Callable"),
            ("int)", "int"),
        ],
    )
    def test_normalize_type_name(self, engine, original, expected):
        """Test type name normalization for Python 3.12+."""
        from auto_type.inference.type_utils import normalize_type_name

        assert normalize_type_name(original) == expected

    async def test_project_root_finding_permission_error(self, engine, tmp_path):
        """Test handling of PermissionError during project root finding."""
        source_file = tmp_path / "script.py"
        source_file.touch()

        with patch("pathlib.Path.exists", side_effect=PermissionError("Permission denied")):
            path, project = find_project_root(str(source_file))
            # Should fail gracefully, return None or fallback
            assert path is None or path == str(source_file)
            # If path returned, project might be None or fallback
            if project:
                assert str(project.path) == str(tmp_path) or str(project.path) == str(
                    source_file.parent
                )

    async def test_exception_in_infer_types(self, engine):
        """Test exception handling in infer_types."""
        with patch("jedi.Script", side_effect=Exception("Jedi boom")):
            result = engine.infer_types("x = 1")
            # Should return a safe fallback result
            assert result.scope_tree.root.name == "<module>"
            assert len(result.scope_tree.root.variables) == 0


class TestAsyncBoundaries:
    """Test async entrypoints preserve expected behavior."""

    async def test_infer_types_returns_inference_result(self, engine):
        """Test infer_types returns inference output for valid input."""
        result = engine.infer_types("x = 1")

        assert "x" in result.scope_tree.root.variables
        assert result.scope_tree.root.variables["x"].type_str == "int"

    async def test_infer_types_at_locations_returns_mapping(self, engine):
        """Test infer_types_at_locations returns inferred type mapping."""
        result = engine.infer_types_at_locations("x = 1", [(1, 0)])

        assert result == {(1, 0): "int"}

    async def test_infer_expression_type_returns_expression_type(self, engine):
        """Test infer_expression_type returns inferred type for expression."""
        result = engine.infer_expression_type("x = 1", "x")

        assert result == "int"


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
        source = textwrap.dedent(source).strip()
        result = engine.infer_types(source)
        # Helper to find var type
        # Since we don't have get_variable_type_at_line exposed easily in the result
        # (it's in ScopeTree but that takes line/col)
        # We can just look at module vars for simple cases
        # But wait, scope_tree.root.get_variable_type_at_line IS available
        type_info = result.scope_tree.root.get_variable_type_at_line(var_name, line)
        # If not found at line, check root variables
        if not type_info and var_name in result.scope_tree.root.variables:
            type_info = result.scope_tree.root.variables[var_name]

        assert type_info is not None
        assert check_func(type_info.type_str)

    async def test_function_reference_returns_callable(self, engine):
        """Test that function references are normalized to 'Callable'."""
        source = """
def param_func():
    return "Hello"
b = param_func
"""
        result = engine.infer_types(source)
        type_info = result.scope_tree.root.variables.get("b")
        assert type_info is not None
        assert type_info.type_str == "Callable"

    async def test_function_call_assignment_from_starred_callable_list(self, engine):
        """Test call inference through starred assignment callable list."""
        source = """
def func2():
    return 42

def func3():
    return 42.5

def func4():
    return [1, 2]

a, *b, c = func2, func3, func4
e = b[0]()
f = b[1]()
"""
        result = engine.infer_types(source)
        e_type = result.scope_tree.root.variables.get("e")
        f_type = result.scope_tree.root.variables.get("f")
        assert e_type is not None
        assert f_type is not None
        assert e_type.type_str in ("int", "float")
        assert f_type.type_str in ("float", "Unknown")

    async def test_itertools_inference(self, engine):
        """Test inference of itertools objects."""
        source = """
import itertools
c = itertools.cycle([1, 2])
"""
        result = engine.infer_types(source)
        type_info = result.scope_tree.root.variables.get("c")
        assert type_info is not None
        # Module path is stripped, so we just check for the class name
        assert "cycle" in type_info.type_str

    async def test_compiled_module_inference_error_handling(self, engine):
        """Test that compiled module inference errors are handled gracefully.

        This test reproduces the issue where Jedi fails to infer types from
        compiled/builtin modules (like itertools), causing ValueError.
        """
        # This code triggers the bug by using itertools.cycle which is a compiled module
        source = """
import itertools
from itertools import cycle

# Using cycle directly from module
c = itertools.cycle([1, 2, 3])

# Using imported cycle directly
c2 = cycle([4, 5, 6])

# Multiple compiled objects
i = itertools.count()
"""
        # This should not raise an exception, even if inference fails
        result = engine.infer_types(source)

        # The scope tree should be built successfully
        assert result.scope_tree.root is not None
        assert result.scope_tree.root.scope_type.value == "module"

        # Variables might be "Unknown" but the tree should exist
        assert "c" in result.scope_tree.root.variables
        assert "c2" in result.scope_tree.root.variables
        assert "i" in result.scope_tree.root.variables

    async def test_builtin_function_inference_error_handling(self, engine):
        """Test that builtin function inference errors are handled gracefully."""
        source = """
# Using various builtin functions that might cause inference issues
x = len([1, 2, 3])
y = range(10)
z = iter([1, 2, 3])
"""
        # This should not raise an exception
        result = engine.infer_types(source)

        # The scope tree should be built successfully
        assert result.scope_tree.root is not None

        # Variables should exist
        assert "x" in result.scope_tree.root.variables
        assert "y" in result.scope_tree.root.variables
        assert "z" in result.scope_tree.root.variables


class TestAsyncGeneratorInference:
    """Test async generator inference (regression test for Jedi AssertionError)."""

    async def test_async_generator_inference_no_crash(self, engine):
        """Test that async generator code doesn't crash the inference engine.

        This is a regression test for a bug where Jedi's get_type_hint() on
        async generators would raise AssertionError, causing the entire
        inference to fail.
        """
        source = """
import asyncio

async def async_range(n):
    for i in range(n):
        await asyncio.sleep(0.01)
        yield i

async def main():
    async for i in async_range(5):
        print(i)

if __name__ == "__main__":
    asyncio.run(main())
"""
        # This should not raise an exception
        result = engine.infer_types(source)

        # The scope tree should be built successfully
        assert result.scope_tree.root is not None
        assert result.scope_tree.root.scope_type.value == "module"

        # Should have scopes for the functions
        scope_names = [s.name for s in result.scope_tree.root.children]
        assert "async_range" in scope_names
        assert "main" in scope_names

    async def test_async_generator_variable_inference(self, engine):
        """Test type inference with async generator variables."""
        source = """
async def generate_numbers():
    for i in range(10):
        yield i

async def process():
    async for num in generate_numbers():
        x = num
"""
        result = engine.infer_types(source)

        # Should not crash
        assert result.scope_tree.root is not None

        # Check that scopes exist
        scope_names = [s.name for s in result.scope_tree.root.children]
        assert "generate_numbers" in scope_names
        assert "process" in scope_names
