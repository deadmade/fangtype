"""Jedi inference of attribute access, literal-container attrs, and optional widening."""


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


class TestLiteralContainerAttributes:
    """Homogeneous literal containers parameterize attribute types."""

    def test_attribute_literal_containers_parameterized(self, engine) -> None:
        source = (
            "class C:\n"
            "    def __init__(self):\n"
            "        self.names = ['a', 'b']\n"
            "        self.counts = {'x': 1}\n"
            "        self.empty = []\n"
        )
        result = engine.infer_types(source)
        scope = result.scope_tree.get_function_scope_by_qualified_name("__init__")
        assert scope is not None
        assert scope.attributes["names"].type_str == "list[str]"
        assert scope.attributes["counts"].type_str == "dict[str, int]"
        assert scope.attributes["empty"].type_str == "list"
