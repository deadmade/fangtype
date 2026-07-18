"""Jedi inference across async boundaries and async generators."""


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


class TestAsyncGeneratorInference:
    """Test async generator inference (regression test for Jedi AssertionError)."""

    async def test_async_generator_inference_no_crash(self, engine):
        """Regression: async generator must not crash inference (Jedi get_type_hint assert)."""
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
