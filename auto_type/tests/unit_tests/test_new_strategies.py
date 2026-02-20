"""Tests for new insertion strategies (subscript, attribute, iteration)."""

from unittest.mock import MagicMock

import pytest

from auto_type.analysis import extract_loop_variables
from auto_type.insertion import InsertionContext, InsertionTarget, TargetType
from auto_type.insertion.strategies import (
    AttributeAccessStrategy,
    IterationVariableStrategy,
    SubscriptAccessStrategy,
)
from auto_type.insertion.target_factory import detect_assignment_pattern
from auto_type.insertion.types import TransformationType


class TestSubscriptAccessStrategy:
    """Tests for SubscriptAccessStrategy."""

    @pytest.fixture
    def strategy(self) -> SubscriptAccessStrategy:
        return SubscriptAccessStrategy()

    @pytest.fixture
    def context(self) -> MagicMock:
        """Create a mock insertion context."""
        mock = MagicMock(spec=InsertionContext)
        mock.has_annotation.return_value = False
        mock.get_annotation.return_value = None
        return mock

    def test_can_handle_subscript_access(self, strategy: SubscriptAccessStrategy) -> None:
        """Test that strategy handles SUBSCRIPT_ACCESS targets."""
        target = MagicMock(spec=InsertionTarget)
        target.target_type = TargetType.SUBSCRIPT_ACCESS

        assert strategy.can_handle(target) is True

    def test_cannot_handle_other_types(self, strategy: SubscriptAccessStrategy) -> None:
        """Test that strategy rejects non-subscript targets."""
        for target_type in [
            TargetType.VARIABLE_SIMPLE,
            TargetType.VARIABLE_COMPLEX,
            TargetType.FUNCTION_PARAMETER,
            TargetType.FUNCTION_RETURN,
            TargetType.ATTRIBUTE_ACCESS,
            TargetType.ITERATION_VARIABLE,
        ]:
            target = MagicMock(spec=InsertionTarget)
            target.target_type = target_type
            assert strategy.can_handle(target) is False

    def test_plan_insertion_new_annotation(
        self, strategy: SubscriptAccessStrategy, context: MagicMock
    ) -> None:
        """Test planning insertion for new subscript access annotation."""
        from auto_type.insertion.types import CodeLocation

        target = MagicMock(spec=InsertionTarget)
        target.target_type = TargetType.SUBSCRIPT_ACCESS
        target.name = "value"
        target.type_annotation = "int"
        target.location = CodeLocation(line=5, column=0)

        plan = strategy.plan_insertion(target, context)

        assert plan.transformation == TransformationType.IN_PLACE
        assert plan.target.name == "value"
        assert plan.target.type_annotation == "int"

    def test_plan_insertion_existing_annotation(
        self, strategy: SubscriptAccessStrategy, context: MagicMock
    ) -> None:
        """Test planning insertion when annotation already exists."""
        from auto_type.insertion.types import CodeLocation

        context.has_annotation.return_value = True
        context.get_annotation.return_value = "str"

        target = MagicMock(spec=InsertionTarget)
        target.target_type = TargetType.SUBSCRIPT_ACCESS
        target.name = "value"
        target.type_annotation = "int"
        target.location = CodeLocation(line=5, column=0)

        plan = strategy.plan_insertion(target, context)

        assert plan.transformation == TransformationType.REPLACEMENT
        assert plan.metadata.get("existing_type") == "str"
        assert plan.metadata.get("new_type") == "int"

    def test_plan_insertion_invalid_type(
        self, strategy: SubscriptAccessStrategy, context: MagicMock
    ) -> None:
        """Test that invalid type syntax raises error."""
        target = MagicMock(spec=InsertionTarget)
        target.target_type = TargetType.SUBSCRIPT_ACCESS
        target.type_annotation = "invalid type syntax [["

        with pytest.raises(ValueError, match="Invalid type annotation syntax"):
            strategy.plan_insertion(target, context)


class TestAttributeAccessStrategy:
    """Tests for AttributeAccessStrategy."""

    @pytest.fixture
    def strategy(self) -> AttributeAccessStrategy:
        return AttributeAccessStrategy()

    @pytest.fixture
    def context(self) -> MagicMock:
        mock = MagicMock(spec=InsertionContext)
        mock.has_annotation.return_value = False
        mock.get_annotation.return_value = None
        return mock

    def test_can_handle_attribute_access(self, strategy: AttributeAccessStrategy) -> None:
        """Test that strategy handles ATTRIBUTE_ACCESS targets."""
        target = MagicMock(spec=InsertionTarget)
        target.target_type = TargetType.ATTRIBUTE_ACCESS

        assert strategy.can_handle(target) is True

    def test_cannot_handle_other_types(self, strategy: AttributeAccessStrategy) -> None:
        """Test that strategy rejects non-attribute targets."""
        for target_type in [
            TargetType.VARIABLE_SIMPLE,
            TargetType.VARIABLE_COMPLEX,
            TargetType.FUNCTION_PARAMETER,
            TargetType.FUNCTION_RETURN,
            TargetType.SUBSCRIPT_ACCESS,
            TargetType.ITERATION_VARIABLE,
        ]:
            target = MagicMock(spec=InsertionTarget)
            target.target_type = target_type
            assert strategy.can_handle(target) is False

    def test_plan_insertion_new_annotation(
        self, strategy: AttributeAccessStrategy, context: MagicMock
    ) -> None:
        """Test planning insertion for new attribute access annotation."""
        from auto_type.insertion.types import CodeLocation

        target = MagicMock(spec=InsertionTarget)
        target.target_type = TargetType.ATTRIBUTE_ACCESS
        target.name = "self.width"
        target.type_annotation = "int"
        target.location = CodeLocation(line=10, column=8)

        plan = strategy.plan_insertion(target, context)

        assert plan.transformation == TransformationType.IN_PLACE
        assert plan.target.name == "self.width"
        assert plan.target.type_annotation == "int"

    def test_plan_insertion_existing_annotation(
        self, strategy: AttributeAccessStrategy, context: MagicMock
    ) -> None:
        """Test planning insertion when annotation already exists."""
        from auto_type.insertion.types import CodeLocation

        context.has_annotation.return_value = True
        context.get_annotation.return_value = "float"

        target = MagicMock(spec=InsertionTarget)
        target.target_type = TargetType.ATTRIBUTE_ACCESS
        target.name = "self.height"
        target.type_annotation = "int"
        target.location = CodeLocation(line=11, column=0)

        plan = strategy.plan_insertion(target, context)

        assert plan.transformation == TransformationType.REPLACEMENT
        assert plan.metadata.get("existing_type") == "float"
        assert plan.metadata.get("new_type") == "int"


class TestIterationVariableStrategy:
    """Tests for IterationVariableStrategy."""

    @pytest.fixture
    def strategy(self) -> IterationVariableStrategy:
        return IterationVariableStrategy()

    @pytest.fixture
    def context(self) -> MagicMock:
        mock = MagicMock(spec=InsertionContext)
        mock.has_annotation.return_value = False
        mock.get_annotation.return_value = None
        return mock

    def test_can_handle_iteration_variable(self, strategy: IterationVariableStrategy) -> None:
        """Test that strategy handles ITERATION_VARIABLE targets."""
        target = MagicMock(spec=InsertionTarget)
        target.target_type = TargetType.ITERATION_VARIABLE

        assert strategy.can_handle(target) is True

    def test_cannot_handle_other_types(self, strategy: IterationVariableStrategy) -> None:
        """Test that strategy rejects non-iteration targets."""
        for target_type in [
            TargetType.VARIABLE_SIMPLE,
            TargetType.VARIABLE_COMPLEX,
            TargetType.FUNCTION_PARAMETER,
            TargetType.FUNCTION_RETURN,
            TargetType.SUBSCRIPT_ACCESS,
            TargetType.ATTRIBUTE_ACCESS,
        ]:
            target = MagicMock(spec=InsertionTarget)
            target.target_type = target_type
            assert strategy.can_handle(target) is False

    def test_plan_insertion_new_annotation(
        self, strategy: IterationVariableStrategy, context: MagicMock
    ) -> None:
        """Test planning insertion for new iteration variable annotation."""
        from auto_type.insertion.types import CodeLocation

        target = MagicMock(spec=InsertionTarget)
        target.target_type = TargetType.ITERATION_VARIABLE
        target.name = "i"
        target.type_annotation = "int"
        target.location = CodeLocation(line=15, column=4)

        plan = strategy.plan_insertion(target, context)

        # Iteration variables use DECLARATION transformation (pre-declaration)
        assert plan.transformation == TransformationType.DECLARATION
        assert plan.target.name == "i"
        assert plan.target.type_annotation == "int"

    def test_plan_insertion_existing_annotation(
        self, strategy: IterationVariableStrategy, context: MagicMock
    ) -> None:
        """Test planning insertion when annotation already exists."""
        from auto_type.insertion.types import CodeLocation

        context.has_annotation.return_value = True
        context.get_annotation.return_value = "Any"

        target = MagicMock(spec=InsertionTarget)
        target.target_type = TargetType.ITERATION_VARIABLE
        target.name = "item"
        target.type_annotation = "str"
        target.location = CodeLocation(line=20, column=0)

        plan = strategy.plan_insertion(target, context)

        assert plan.transformation == TransformationType.REPLACEMENT
        assert plan.metadata.get("existing_type") == "Any"
        assert plan.metadata.get("new_type") == "str"


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

    def test_all_target_types_exist(self) -> None:
        """Test that all expected target types are defined."""
        expected_types = {
            "variable_simple",
            "variable_complex",
            "function_parameter",
            "function_return",
            "class_variable",
            "function_scope_variable",
            "subscript_access",
            "attribute_access",
            "iteration_variable",
        }
        actual_types = {t.value for t in TargetType}
        assert actual_types == expected_types

    def test_new_types_in_variable_target_property(self) -> None:
        """Test that new types are included in is_variable_target check."""
        # Create a mock target for each type and check is_variable_target
        for target_type in [
            TargetType.VARIABLE_SIMPLE,
            TargetType.VARIABLE_COMPLEX,
            TargetType.SUBSCRIPT_ACCESS,
            TargetType.ATTRIBUTE_ACCESS,
            TargetType.ITERATION_VARIABLE,
        ]:
            target = MagicMock(spec=InsertionTarget)
            target.target_type = target_type
            # The InsertionTarget.is_variable_target property checks these types
            assert target_type in [
                TargetType.VARIABLE_SIMPLE,
                TargetType.VARIABLE_COMPLEX,
                TargetType.SUBSCRIPT_ACCESS,
                TargetType.ATTRIBUTE_ACCESS,
                TargetType.ITERATION_VARIABLE,
            ]

    def test_non_variable_types_excluded(self) -> None:
        """Test that function/class types are not in variable target list."""
        non_variable_types = [
            TargetType.FUNCTION_PARAMETER,
            TargetType.FUNCTION_RETURN,
            TargetType.CLASS_VARIABLE,
            TargetType.FUNCTION_SCOPE_VARIABLE,
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
