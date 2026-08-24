"""Jedi inference of union types."""

import textwrap

import pytest


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
        # Look up var type via scope_tree.root.get_variable_type_at_line (line/col based)
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
        """Compiled/builtin module inference errors (e.g. itertools ValueError) handled ok."""
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
