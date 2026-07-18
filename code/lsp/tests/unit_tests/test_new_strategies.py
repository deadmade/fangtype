"""Tests for plan_target: subscript/attribute/iteration insertion planning."""

from unittest.mock import MagicMock

import pytest
from fangtype.analysis import extract_loop_variables
from fangtype.insertion import InsertionContext, InsertionTarget, TargetType
from fangtype.insertion.strategy import plan_target
from fangtype.insertion.target_factory import detect_assignment_pattern
from fangtype.insertion.types import CodeLocation, TransformationType

# (own target type, transformation used for a NEW annotation)
STRATEGY_CASES = [
    pytest.param(TargetType.SUBSCRIPT_ACCESS, TransformationType.IN_PLACE, id="subscript"),
    pytest.param(TargetType.ATTRIBUTE_ACCESS, TransformationType.IN_PLACE, id="attribute"),
    pytest.param(TargetType.ITERATION_VARIABLE, TransformationType.DECLARATION, id="iteration"),
]


@pytest.fixture
def context() -> MagicMock:
    """A mock insertion context with no pre-existing annotation."""
    mock = MagicMock(spec=InsertionContext)
    mock.has_annotation.return_value = False
    return mock


@pytest.mark.parametrize("own_type, expected_transformation", STRATEGY_CASES)
class TestInsertionPlanning:
    """Planning behavior for the subscript/attribute/iteration target types."""

    def test_plan_new_annotation(self, own_type, expected_transformation, context) -> None:
        target = MagicMock(spec=InsertionTarget)
        target.target_type = own_type
        target.name = "value"
        target.type_annotation = "int"
        target.location = CodeLocation(line=5, column=0)

        plan = plan_target(target, context)

        assert plan is not None
        assert plan.transformation == expected_transformation
        assert plan.target.name == "value"
        assert plan.target.type_annotation == "int"

    def test_plan_existing_annotation(self, own_type, expected_transformation, context) -> None:
        context.has_annotation.return_value = True

        target = MagicMock(spec=InsertionTarget)
        target.target_type = own_type
        target.name = "value"
        target.type_annotation = "int"
        target.location = CodeLocation(line=5, column=0)

        plan = plan_target(target, context)

        assert plan is not None
        assert plan.transformation == TransformationType.REPLACEMENT
        assert plan.metadata.get("new_type") == "int"


def test_plan_invalid_type(context: MagicMock) -> None:
    """Invalid type syntax that can't be sanitized raises ValueError."""
    target = MagicMock(spec=InsertionTarget)
    target.target_type = TargetType.SUBSCRIPT_ACCESS
    target.type_annotation = "invalid type syntax [["

    with pytest.raises(ValueError, match="Invalid type annotation syntax"):
        plan_target(target, context)


class TestPatternDetectionHelpers:
    """Tests for assignment pattern detection helpers."""

    def test_detect_subscript_access_pattern(self) -> None:
        """Test detection of subscript access assignments."""
        source = """
data = {"key": 42}
value = data["key"]
"""
        # Line 3 (0-based: 2), variable 'value'
        target_type = detect_assignment_pattern(source, "value", 2)
        assert target_type == TargetType.SUBSCRIPT_ACCESS

    def test_detect_attribute_access_pattern(self) -> None:
        """Test detection of attribute access assignments."""
        source = """
class MyClass:
    def method(self):
        self.value = 100
"""
        # Line 4 (0-based: 3), variable 'self.value'
        target_type = detect_assignment_pattern(source, "self.value", 3)
        assert target_type == TargetType.ATTRIBUTE_ACCESS

    def test_detect_iteration_variable_pattern(self) -> None:
        """Test detection of iteration variables in for loops."""
        source = """
for i in range(10):
    pass
"""
        # Line 2 (0-based: 1), variable 'i'
        target_type = detect_assignment_pattern(source, "i", 1)
        assert target_type == TargetType.ITERATION_VARIABLE

    def test_detect_simple_variable_pattern(self) -> None:
        """Test detection of simple variable assignments."""
        source = """
x = 42
y = "hello"
"""
        target_type = detect_assignment_pattern(source, "x", 1)
        assert target_type == TargetType.VARIABLE_SIMPLE

    def test_detect_complex_variable_pattern(self) -> None:
        """Test detection of complex (tuple unpacking) assignments."""
        source = """
a, b = 1, 2
"""
        target_type = detect_assignment_pattern(source, "a", 1)
        assert target_type == TargetType.VARIABLE_COMPLEX

    def test_extract_loop_variables_simple(self) -> None:
        """Test extraction of simple loop variables."""
        import ast

        source = "for i in range(10): pass"
        tree = ast.parse(source)
        for_node = tree.body[0]
        variables = extract_loop_variables(for_node.target)
        assert variables == ["i"]

    def test_extract_loop_variables_tuple_unpacking(self) -> None:
        """Test extraction of tuple unpacking loop variables."""
        import ast

        source = "for key, value in d.items(): pass"
        tree = ast.parse(source)
        for_node = tree.body[0]
        variables = extract_loop_variables(for_node.target)
        assert set(variables) == {"key", "value"}

    def test_detect_iteration_variable_in_tuple_unpacking(self) -> None:
        """Test detection of iteration variables with tuple unpacking."""
        source = """
for key, value in d.items():
    pass
"""
        # Line 2 (0-based: 1), variable 'key'
        target_type = detect_assignment_pattern(source, "key", 1)
        assert target_type == TargetType.ITERATION_VARIABLE

        # Line 2 (0-based: 1), variable 'value'
        target_type = detect_assignment_pattern(source, "value", 1)
        assert target_type == TargetType.ITERATION_VARIABLE

    def test_fallback_on_syntax_error(self) -> None:
        """Test that syntax errors fall back to VARIABLE_SIMPLE."""
        source = "invalid python syntax [["
        target_type = detect_assignment_pattern(source, "x", 0)
        assert target_type == TargetType.VARIABLE_SIMPLE


class TestTargetTypeEnum:
    """Tests for the TargetType enum values."""

    def test_non_variable_types_excluded(self) -> None:
        """Test that function/class types are not in variable target list."""
        non_variable_types = [
            TargetType.FUNCTION_PARAMETER,
            TargetType.FUNCTION_RETURN,
        ]
        variable_types = [
            TargetType.VARIABLE_SIMPLE,
            TargetType.VARIABLE_COMPLEX,
            TargetType.SUBSCRIPT_ACCESS,
            TargetType.ATTRIBUTE_ACCESS,
            TargetType.ITERATION_VARIABLE,
        ]

        for t in non_variable_types:
            assert t not in variable_types
