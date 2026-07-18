"""Jedi inference of function returns, variables, parameters, and expressions."""

import textwrap

import pytest


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

    async def test_return_union_from_pruned_match_branches(self, engine):
        """Jedi prunes match/if branches to one type; AST recovery restores the union."""
        source = """
def func(value):
    match value:
        case "case1":
            return 42
        case "case2":
            return "hello"
        case _:
            return "unknown"
"""
        result = engine.infer_types(source)

        func_scope = result.scope_tree.root.children[0]
        assert func_scope.return_type is not None
        type_str = func_scope.return_type.type_str
        assert "int" in type_str and "str" in type_str

    async def test_single_return_not_spuriously_unioned(self, engine):
        """A single-typed function must not gain a spurious union from AST recovery."""
        source = """
def only_int(flag):
    if flag:
        return 1
    return 2
"""
        result = engine.infer_types(source)

        func_scope = result.scope_tree.root.children[0]
        assert func_scope.return_type is not None
        assert "str" not in func_scope.return_type.type_str
        assert "int" in func_scope.return_type.type_str

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
