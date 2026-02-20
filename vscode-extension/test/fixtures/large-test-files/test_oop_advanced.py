"""Advanced Object-Oriented Programming patterns for testing Auto Type extension.

This module demonstrates complex OOP patterns including:
- Abstract base classes and protocols
- Multiple inheritance and mixins
- Generic classes with type parameters
- Property decorators
- Dataclasses with complex fields
- Class/static methods
- Method overriding and super() calls

Expected: Accurate type hints for self, instance attributes, properties, and inherited methods.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Generic, Protocol, TypeVar

# =============================================================================
# TYPE VARIABLES AND GENERIC DEFINITIONS
# =============================================================================

T = TypeVar("T")
K = TypeVar("K")
V = TypeVar("V")
TNum = TypeVar("TNum", int, float)


# =============================================================================
# PROTOCOLS
# =============================================================================


class Drawable(Protocol):
    """Protocol for drawable objects."""

    def draw(self) -> str:
        """Draw the object."""
        ...

    def get_bounds(self) -> tuple[int, int, int, int]:
        """Get bounding box."""
        ...


class Serializable(Protocol):
    """Protocol for serializable objects."""

    def serialize(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        ...

    @classmethod
    def deserialize(cls, data: dict[str, Any]) -> Serializable:
        """Deserialize from dictionary."""
        ...


class Comparable(Protocol):
    """Protocol for comparable objects."""

    def __lt__(self, other: Any) -> bool:
        """Less than comparison."""
        ...

    def __eq__(self, other: Any) -> bool:
        """Equality comparison."""
        ...


# =============================================================================
# ABSTRACT BASE CLASSES
# =============================================================================


class Shape(ABC):
    """Abstract base class for geometric shapes."""

    def __init__(self, name):
        self.name = name  # Expected hint: self.name: str
        self._color = "black"  # Expected hint: self._color: str
        self._visible = True  # Expected hint: self._visible: bool

    @abstractmethod
    def area(self):
        """Calculate area."""
        ...

    @abstractmethod
    def perimeter(self):
        """Calculate perimeter."""
        ...

    @property
    def color(self):
        """Get shape color."""
        return self._color  # Expected hint: return type: str

    @color.setter
    def color(self, value):
        """Set shape color."""
        self._color = value

    @property
    def visible(self):
        """Check if shape is visible."""
        return self._visible  # Expected hint: return type: bool

    def describe(self):
        """Get shape description."""
        desc = f"{self.name} ({self.color})"  # Expected hint: desc: str
        return desc

    def scale(self, factor):
        """Scale the shape by a factor."""
        scaled_factor = abs(factor)  # Expected hint: scaled_factor: int | float
        return scaled_factor


class Container(ABC, Generic[T]):
    """Abstract generic container."""

    def __init__(self):
        self._items = []  # Expected hint: self._items: list

    @abstractmethod
    def add(self, item: T) -> None:
        """Add an item to container."""
        ...

    @abstractmethod
    def remove(self, item: T) -> bool:
        """Remove an item from container."""
        ...

    def count(self):
        """Get number of items."""
        return len(self._items)  # Expected hint: return type: int

    def is_empty(self):
        """Check if container is empty."""
        empty = len(self._items) == 0  # Expected hint: empty: bool
        return empty

    def clear(self):
        """Remove all items."""
        self._items.clear()
        cleared_count = 0  # Expected hint: cleared_count: int
        return cleared_count


# =============================================================================
# CONCRETE SHAPE IMPLEMENTATIONS
# =============================================================================


class Rectangle(Shape):
    """Rectangle implementation."""

    def __init__(self, name, width, height):
        super().__init__(name)
        self.width = width  # Expected hint: self.width: int | float
        self.height = height  # Expected hint: self.height: int | float

    def area(self):
        """Calculate rectangle area."""
        result = self.width * self.height  # Expected hint: result: int | float
        return result

    def perimeter(self):
        """Calculate rectangle perimeter."""
        result = 2 * (self.width + self.height)  # Expected hint: result: int | float
        return result

    def is_square(self):
        """Check if rectangle is a square."""
        return self.width == self.height  # Expected hint: return type: bool

    def diagonal(self):
        """Calculate diagonal length."""
        squared = self.width**2 + self.height**2  # Expected hint: squared: int | float
        diag = squared**0.5  # Expected hint: diag: float
        return diag


class Circle(Shape):
    """Circle implementation."""

    PI = 3.14159  # Class variable - Expected hint: PI: float

    def __init__(self, name, radius):
        super().__init__(name)
        self.radius = radius  # Expected hint: self.radius: int | float
        self._cached_area = None  # Expected hint: self._cached_area: None

    def area(self):
        """Calculate circle area."""
        if self._cached_area is None:
            calculated = self.PI * self.radius**2  # Expected hint: calculated: float
            self._cached_area = calculated

        return self._cached_area  # Expected hint: return type: float | None

    def perimeter(self):
        """Calculate circle circumference."""
        result = 2 * self.PI * self.radius  # Expected hint: result: float
        return result

    def diameter(self):
        """Get circle diameter."""
        diam = 2 * self.radius  # Expected hint: diam: int | float
        return diam

    @classmethod
    def from_diameter(cls, name, diameter):
        """Create circle from diameter."""
        radius = diameter / 2  # Expected hint: radius: int | float
        return cls(name, radius)  # Expected hint: return type: Circle


class Triangle(Shape):
    """Triangle implementation."""

    def __init__(self, name, side_a, side_b, side_c):
        super().__init__(name)
        self.side_a = side_a  # Expected hint: self.side_a: int | float
        self.side_b = side_b  # Expected hint: self.side_b: int | float
        self.side_c = side_c  # Expected hint: self.side_c: int | float

    def area(self):
        """Calculate triangle area using Heron's formula."""
        s = self.perimeter() / 2  # Expected hint: s: int | float
        area_squared = (
            s * (s - self.side_a) * (s - self.side_b) * (s - self.side_c)
        )  # Expected hint: area_squared: int | float
        result = area_squared**0.5  # Expected hint: result: float
        return result

    def perimeter(self):
        """Calculate triangle perimeter."""
        result = (
            self.side_a + self.side_b + self.side_c
        )  # Expected hint: result: int | float
        return result

    def is_valid(self):
        """Check if triangle sides form a valid triangle."""
        check1 = self.side_a + self.side_b > self.side_c  # Expected hint: check1: bool
        check2 = self.side_b + self.side_c > self.side_a  # Expected hint: check2: bool
        check3 = self.side_a + self.side_c > self.side_b  # Expected hint: check3: bool
        return check1 and check2 and check3  # Expected hint: return type: bool

    def is_equilateral(self):
        """Check if triangle is equilateral."""
        return (
            self.side_a == self.side_b == self.side_c
        )  # Expected hint: return type: bool


# =============================================================================
# MIXINS
# =============================================================================


class LoggingMixin:
    """Mixin to add logging capabilities."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._log = []  # Expected hint: self._log: list

    def log(self, message):
        """Add a log message."""
        entry = f"[LOG] {message}"  # Expected hint: entry: str
        self._log.append(entry)

    def get_logs(self):
        """Get all log messages."""
        return self._log.copy()  # Expected hint: return type: list

    def clear_logs(self):
        """Clear all logs."""
        count = len(self._log)  # Expected hint: count: int
        self._log.clear()
        return count


class ValidationMixin:
    """Mixin to add validation capabilities."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._errors = []  # Expected hint: self._errors: list

    def add_error(self, error):
        """Add a validation error."""
        self._errors.append(error)

    def is_valid(self):
        """Check if object has no errors."""
        valid = len(self._errors) == 0  # Expected hint: valid: bool
        return valid

    def get_errors(self):
        """Get all validation errors."""
        return self._errors.copy()  # Expected hint: return type: list


class TimestampMixin:
    """Mixin to add timestamp tracking."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from datetime import datetime

        self.created_at = datetime.now()  # Expected hint: self.created_at: datetime

    def age_seconds(self):
        """Get age in seconds."""
        from datetime import datetime

        now = datetime.now()  # Expected hint: now: datetime
        delta = now - self.created_at  # Expected hint: delta: timedelta
        seconds = delta.total_seconds()  # Expected hint: seconds: float
        return seconds


# =============================================================================
# MULTIPLE INHERITANCE
# =============================================================================


class ValidatedShape(Shape, ValidationMixin, LoggingMixin):
    """Shape with validation and logging."""

    def __init__(self, name):
        super().__init__(name)
        self.log(f"Created shape: {name}")

    def validate_dimensions(self):
        """Validate shape dimensions (to be overridden)."""
        self.log("Validating dimensions")
        return True


class ValidatedRectangle(ValidatedShape):
    """Rectangle with validation."""

    def __init__(self, name, width, height):
        # Initialize parent classes
        Shape.__init__(self, name)
        ValidationMixin.__init__(self)
        LoggingMixin.__init__(self)

        self.width = width  # Expected hint: self.width: int | float
        self.height = height  # Expected hint: self.height: int | float

        self.validate_dimensions()

    def area(self):
        """Calculate area."""
        return self.width * self.height

    def perimeter(self):
        """Calculate perimeter."""
        return 2 * (self.width + self.height)

    def validate_dimensions(self):
        """Validate rectangle dimensions."""
        self.log("Validating rectangle dimensions")

        if self.width <= 0:
            self.add_error("Width must be positive")
        if self.height <= 0:
            self.add_error("Height must be positive")

        valid = self.is_valid()  # Expected hint: valid: bool
        return valid


# =============================================================================
# GENERIC CONTAINER IMPLEMENTATIONS
# =============================================================================


class Stack(Container[T]):
    """Stack implementation (LIFO)."""

    def add(self, item):
        """Push item onto stack."""
        self._items.append(item)
        size = len(self._items)  # Expected hint: size: int
        return size

    def remove(self, item):
        """Remove specific item from stack."""
        if item in self._items:
            self._items.remove(item)
            return True
        return False

    def pop(self):
        """Pop top item from stack."""
        if self._items:
            item = self._items.pop()  # Expected hint: item: T
            return item
        return None

    def peek(self):
        """Peek at top item without removing."""
        if self._items:
            return self._items[-1]  # Expected hint: return type: T
        return None

    def size(self):
        """Get stack size."""
        count = len(self._items)  # Expected hint: count: int
        return count


class Queue(Container[T]):
    """Queue implementation (FIFO)."""

    def add(self, item):
        """Enqueue item."""
        self._items.append(item)

    def remove(self, item):
        """Remove specific item from queue."""
        if item in self._items:
            self._items.remove(item)
            return True
        return False

    def dequeue(self):
        """Dequeue front item."""
        if self._items:
            item = self._items.pop(0)  # Expected hint: item: T
            return item
        return None

    def front(self):
        """Get front item without removing."""
        if self._items:
            return self._items[0]  # Expected hint: return type: T
        return None


class PriorityQueue(Container[tuple[int, T]]):
    """Priority queue with integer priorities."""

    def add(self, item):
        """Add item with priority."""
        self._items.append(item)
        # Sort by priority (lower number = higher priority)
        self._items.sort(key=lambda x: x[0])

    def remove(self, item):
        """Remove specific item."""
        if item in self._items:
            self._items.remove(item)
            return True
        return False

    def dequeue(self):
        """Dequeue highest priority item."""
        if self._items:
            priority_item = self._items.pop(
                0
            )  # Expected hint: priority_item: tuple[int, T]
            return priority_item
        return None

    def peek_priority(self):
        """Get priority of next item."""
        if self._items:
            priority, _ = self._items[0]  # Expected hint: priority: int
            return priority
        return None


# =============================================================================
# DATACLASSES WITH COMPLEX TYPES
# =============================================================================


@dataclass
class Point:
    """2D point."""

    x: float
    y: float

    def distance_to(self, other):
        """Calculate distance to another point."""
        dx = self.x - other.x  # Expected hint: dx: float
        dy = self.y - other.y  # Expected hint: dy: float
        dist = (dx**2 + dy**2) ** 0.5  # Expected hint: dist: float
        return dist

    def midpoint(self, other):
        """Calculate midpoint between two points."""
        mid_x = (self.x + other.x) / 2  # Expected hint: mid_x: float
        mid_y = (self.y + other.y) / 2  # Expected hint: mid_y: float
        return Point(mid_x, mid_y)  # Expected hint: return type: Point


@dataclass
class Line:
    """Line segment defined by two points."""

    start: Point
    end: Point

    def length(self):
        """Calculate line length."""
        return self.start.distance_to(self.end)  # Expected hint: return type: float

    def midpoint(self):
        """Get line midpoint."""
        return self.start.midpoint(self.end)  # Expected hint: return type: Point

    def slope(self):
        """Calculate line slope."""
        dx = self.end.x - self.start.x  # Expected hint: dx: float
        dy = self.end.y - self.start.y  # Expected hint: dy: float

        if dx == 0:
            return None  # Vertical line

        slope_val = dy / dx  # Expected hint: slope_val: float
        return slope_val


@dataclass
class Polygon:
    """Polygon defined by multiple points."""

    points: list[Point] = field(default_factory=list)
    closed: bool = True

    def add_point(self, point):
        """Add a point to polygon."""
        self.points.append(point)
        count = len(self.points)  # Expected hint: count: int
        return count

    def perimeter(self):
        """Calculate polygon perimeter."""
        if len(self.points) < 2:
            return 0.0

        total = 0.0  # Expected hint: total: float

        for i in range(len(self.points) - 1):
            p1 = self.points[i]  # Expected hint: p1: Point
            p2 = self.points[i + 1]  # Expected hint: p2: Point
            distance = p1.distance_to(p2)  # Expected hint: distance: float
            total += distance

        if self.closed and len(self.points) > 2:
            last_distance = self.points[-1].distance_to(
                self.points[0]
            )  # Expected hint: last_distance: float
            total += last_distance

        return total

    def bounds(self):
        """Get bounding box."""
        if not self.points:
            return None

        min_x = min(p.x for p in self.points)  # Expected hint: min_x: float
        max_x = max(p.x for p in self.points)  # Expected hint: max_x: float
        min_y = min(p.y for p in self.points)  # Expected hint: min_y: float
        max_y = max(p.y for p in self.points)  # Expected hint: max_y: float

        return (min_x, min_y, max_x, max_y)


# =============================================================================
# FACTORY PATTERN
# =============================================================================


class ShapeFactory:
    """Factory for creating shapes."""

    _registry = {}  # Expected hint: _registry: dict (class variable)

    @classmethod
    def register(cls, shape_type, shape_class):
        """Register a shape type."""
        cls._registry[shape_type] = shape_class
        count = len(cls._registry)  # Expected hint: count: int
        return count

    @classmethod
    def create(cls, shape_type, *args, **kwargs):
        """Create a shape by type."""
        shape_class = cls._registry.get(
            shape_type
        )  # Expected hint: shape_class: type | None

        if shape_class is None:
            raise ValueError(f"Unknown shape type: {shape_type}")

        instance = shape_class(
            *args, **kwargs
        )  # Expected hint: instance: Shape (or subclass)
        return instance

    @classmethod
    def available_types(cls):
        """Get list of available shape types."""
        types = list(cls._registry.keys())  # Expected hint: types: list
        return types


# Register standard shapes
ShapeFactory.register("rectangle", Rectangle)
ShapeFactory.register("circle", Circle)
ShapeFactory.register("triangle", Triangle)


# =============================================================================
# BUILDER PATTERN
# =============================================================================


class PolygonBuilder:
    """Builder for constructing polygons."""

    def __init__(self):
        self._points = []  # Expected hint: self._points: list
        self._closed = True  # Expected hint: self._closed: bool

    def add_point(self, x, y):
        """Add a point."""
        point = Point(x, y)  # Expected hint: point: Point
        self._points.append(point)
        return self  # Fluent interface

    def set_closed(self, closed):
        """Set whether polygon is closed."""
        self._closed = closed
        return self

    def build(self):
        """Build the polygon."""
        polygon = Polygon(
            points=self._points.copy(), closed=self._closed
        )  # Expected hint: polygon: Polygon
        return polygon

    def reset(self):
        """Reset builder."""
        self._points.clear()
        self._closed = True
        return self


# =============================================================================
# STATIC AND CLASS METHODS
# =============================================================================


class MathUtils:
    """Utility class with static and class methods."""

    PI: ClassVar[float] = 3.14159
    E: ClassVar[float] = 2.71828

    @staticmethod
    def add(a, b):
        """Add two numbers."""
        result = a + b  # Expected hint: result: int | float
        return result

    @staticmethod
    def multiply(a, b):
        """Multiply two numbers."""
        result = a * b  # Expected hint: result: int | float
        return result

    @staticmethod
    def distance_2d(x1, y1, x2, y2):
        """Calculate 2D distance."""
        dx = x2 - x1  # Expected hint: dx: int | float
        dy = y2 - y1  # Expected hint: dy: int | float
        dist = (dx**2 + dy**2) ** 0.5  # Expected hint: dist: float
        return dist

    @classmethod
    def circle_area(cls, radius):
        """Calculate circle area using class constant."""
        area = cls.PI * radius**2  # Expected hint: area: float
        return area

    @classmethod
    def circle_circumference(cls, radius):
        """Calculate circle circumference."""
        circ = 2 * cls.PI * radius  # Expected hint: circ: float
        return circ


# =============================================================================
# EXAMPLE USAGE
# =============================================================================


def demonstrate_shapes():
    """Demonstrate shape hierarchy."""
    # Create shapes
    rect = Rectangle("MyRect", 10, 20)  # Expected hint: rect: Rectangle
    circ = Circle("MyCircle", 5)  # Expected hint: circ: Circle
    tri = Triangle("MyTriangle", 3, 4, 5)  # Expected hint: tri: Triangle

    # Calculate areas
    rect_area = rect.area()  # Expected hint: rect_area: int | float
    circ_area = circ.area()  # Expected hint: circ_area: float | None
    tri_area = tri.area()  # Expected hint: tri_area: float

    # Use properties
    rect.color = "red"
    color = rect.color  # Expected hint: color: str

    return [rect, circ, tri]


def demonstrate_containers():
    """Demonstrate generic containers."""
    # Stack of integers
    stack = Stack[int]()  # Expected hint: stack: Stack[int]
    stack.add(1)
    stack.add(2)
    stack.add(3)
    top = stack.pop()  # Expected hint: top: int | None

    # Queue of strings
    queue = Queue[str]()  # Expected hint: queue: Queue[str]
    queue.add("first")
    queue.add("second")
    front = queue.dequeue()  # Expected hint: front: str | None

    return stack, queue


def demonstrate_factory():
    """Demonstrate factory pattern."""
    # Create shapes using factory
    rect = ShapeFactory.create(
        "rectangle", "FactoryRect", 5, 10
    )  # Expected hint: rect: Shape
    circ = ShapeFactory.create(
        "circle", "FactoryCircle", 7
    )  # Expected hint: circ: Shape

    # Get available types
    types = ShapeFactory.available_types()  # Expected hint: types: list

    return rect, circ, types


def demonstrate_builder():
    """Demonstrate builder pattern."""
    builder = PolygonBuilder()  # Expected hint: builder: PolygonBuilder

    # Build a triangle
    triangle = (  # Expected hint: triangle: Polygon
        builder.add_point(0, 0)
        .add_point(1, 0)
        .add_point(0.5, 0.866)
        .set_closed(True)
        .build()
    )

    # Build a square
    builder.reset()
    square = (  # Expected hint: square: Polygon
        builder.add_point(0, 0)
        .add_point(1, 0)
        .add_point(1, 1)
        .add_point(0, 1)
        .set_closed(True)
        .build()
    )

    tri_perim = triangle.perimeter()  # Expected hint: tri_perim: float
    sq_perim = square.perimeter()  # Expected hint: sq_perim: float

    return triangle, square


if __name__ == "__main__":
    shapes = demonstrate_shapes()  # Expected hint: shapes: list
    containers = demonstrate_containers()  # Expected hint: containers: tuple
    factory_results = demonstrate_factory()  # Expected hint: factory_results: tuple
    builder_results = demonstrate_builder()  # Expected hint: builder_results: tuple

    print(f"Created {len(shapes)} shapes")
