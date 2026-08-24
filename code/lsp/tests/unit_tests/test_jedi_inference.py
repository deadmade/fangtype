"""JediInferenceEngine edge cases and TypeEvalPy integration scenarios."""

import ast
from unittest.mock import patch

import jedi

from fangtype.inference.jedi.engine import JediInferenceEngine
from fangtype.utils.settings import Settings


class TestInferenceResilience:
    """A crash in Jedi/parso on one location drops only that location, not the whole file."""

    def test_one_location_crash_does_not_zero_the_file(self, engine):
        source = "a = 1\nb = 'x'\n"
        bad = (2, 0)  # simulate Jedi blowing up on `b`
        good = (1, 0)  # `a` -> int must still be inferred

        real_infer = jedi.Script.infer

        def flaky_infer(self, line=None, column=None, *args, **kwargs):
            if (line, column) == bad:
                raise KeyError("simulated parso parse-cache miss")
            return real_infer(self, line, column, *args, **kwargs)

        # Process the crashing location FIRST, to prove the loop continues past it.
        with patch.object(jedi.Script, "infer", flaky_infer):
            result = engine.infer_types_at_locations(source, [bad, good])

        assert good in result  # neighbor survived (absent before the fix)
        assert bad not in result  # crashing location dropped, not fatal


class TestInferTypesResilience:
    """A transient Jedi/parso failure must not cost the whole file its types."""

    SOURCE = "def f():\n    return 1\n\n\nclass C:\n    pass\n"

    def test_transient_failure_is_retried_and_the_file_survives(self, engine):
        """One parse-cache miss is retried; the file keeps its names.

        Before the fix a single ``KeyError`` from deep inside name resolution unwound
        into a bare ``except`` and the whole file came back with only module scope.
        """
        calls = {"n": 0}
        real_get_names = jedi.Script.get_names

        def flaky_get_names(self, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise KeyError("simulated parso parse-cache miss")
            return real_get_names(self, *args, **kwargs)

        with patch.object(jedi.Script, "get_names", flaky_get_names):
            result = engine.infer_types(self.SOURCE)

        assert calls["n"] >= 2, "the failure should have been retried once"
        assert result.is_complete
        assert len(result.scope_tree.scopes_by_id) > 1, "file kept its scopes"

    def test_permanent_failure_is_not_cacheable(self, engine):
        """A failure that survives the retry still yields a never-cache result."""

        def always_fails(self, *args, **kwargs):
            raise KeyError("simulated parso parse-cache miss")

        with patch.object(jedi.Script, "get_names", always_fails):
            result = engine.infer_types(self.SOURCE)

        assert result.is_complete is False

    def test_no_names_for_a_substantive_module_is_degraded(self, engine):
        """Jedi returning nothing for a module with statements is a failure, not an
        empty file, so it must not be cached and served back."""
        with patch.object(jedi.Script, "get_names", lambda self, *a, **k: []):
            result = engine.infer_types(self.SOURCE)

        assert result.is_complete is False

    def test_a_module_with_no_statements_stays_complete(self, engine):
        """A docstring-only module really has no names; that tree is correct."""
        with patch.object(jedi.Script, "get_names", lambda self, *a, **k: []):
            result = engine.infer_types('"""Only a docstring."""\n')

        assert result.is_complete is True

    def test_syntax_error_is_not_retried(self, engine):
        """A file that does not parse has no types; that is an answer, not a failure."""
        with patch.object(jedi.Script, "get_names") as get_names:
            result = engine.infer_types("def broken(:\n")

        assert result.is_complete is False
        get_names.assert_not_called()


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
        """Empty source yields a bare module scope: no children, no variables."""
        result = engine.infer_types("")

        root = result.scope_tree.root
        assert root.scope_type.value == "module"
        assert root.children == []
        assert root.variables == {}

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

    async def test_infer_types_repeated_calls_are_deterministic(self, engine):
        """Repeated infer_types calls on the same source infer the identical type each run."""
        source = "x = 42"
        results = [engine.infer_types(source) for _ in range(5)]

        first = results[0].scope_tree.root.variables["x"].type_str
        assert first == "int"
        for result in results[1:]:
            assert result.scope_tree.root.variables["x"].type_str == first

    async def test_exception_in_infer_types(self, engine):
        """Test exception handling in infer_types."""
        with patch("jedi.Script", side_effect=Exception("Jedi boom")):
            result = engine.infer_types("x = 1")
            # Should return a safe fallback result
            assert result.scope_tree.root.name == "<module>"
            assert len(result.scope_tree.root.variables) == 0


class TestJediEnvironmentSelection:
    """Jedi follows the project interpreter when set, so a managed venv stays project-aware."""

    def test_uses_project_interpreter_when_set(self):
        engine = JediInferenceEngine(Settings(project_interpreter="/venv/bin/python"))
        sentinel = object()
        with patch("jedi.api.environment.create_environment", return_value=sentinel) as mk:
            env = engine._get_env()
        mk.assert_called_once_with("/venv/bin/python", safe=False)
        assert env is sentinel

    def test_falls_back_to_same_environment_when_create_fails(self):
        engine = JediInferenceEngine(Settings(project_interpreter="/bad/python"))
        sentinel = object()
        with (
            patch("jedi.api.environment.create_environment", side_effect=OSError("nope")),
            patch("jedi.api.environment.SameEnvironment", return_value=sentinel),
        ):
            env = engine._get_env()
        assert env is sentinel

    def test_uses_same_environment_when_no_project_interpreter(self):
        engine = JediInferenceEngine(Settings())
        sentinel = object()
        with (
            patch("jedi.api.environment.create_environment") as mk,
            patch("jedi.api.environment.SameEnvironment", return_value=sentinel),
        ):
            env = engine._get_env()
        mk.assert_not_called()
        assert env is sentinel
