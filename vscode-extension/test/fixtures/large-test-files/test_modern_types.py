"""Modern Python 3.12+ type system features for testing Auto Type extension.

This module demonstrates Python 3.12+ type features including:
- Type aliases (PEP 695)
- Generic syntax with [T] (PEP 695)
- Union types with X | Y
- Literal types
- TypedDict with Required/NotRequired
- Protocol definitions
- Pattern matching type narrowing
- Recursive type aliases
- TypeVar constraints and bounds

Expected: Accurate hints for modern type syntax and proper type inference.
"""

from __future__ import annotations

from typing import (
    Any,
    Literal,
    Never,
    NotRequired,
    Protocol,
    TypedDict,
    TypeVar,
)

# =============================================================================
# TYPE ALIASES (PEP 695 - Python 3.12+)
# =============================================================================

# Simple type aliases
type Point2D = tuple[float, float]
type Point3D = tuple[float, float, float]
type PointND = tuple[float, ...]

# Complex type aliases
type JSON = str | int | float | bool | None | dict[str, "JSON"] | list["JSON"]
type Result[T] = tuple[bool, T | None, str | None]
type Matrix[T] = list[list[T]]

# Recursive types
type TreeNode[T] = tuple[T, list["TreeNode[T]"]]
type LinkedList[T] = tuple[T, "LinkedList[T] | None"]

# =============================================================================
# GENERIC TYPE ALIASES
# =============================================================================

# Generic container aliases
type Stack[T] = list[T]
type Queue[T] = list[T]
type Map[K, V] = dict[K, V]


# =============================================================================
# UNION TYPES (Modern X | Y Syntax)
# =============================================================================


def process_value(value):
    """Process various value types."""
    if isinstance(value, int):
        result = value * 2  # Expected hint: result: int
    elif isinstance(value, str):
        result = value.upper()  # Expected hint: result: str
    elif isinstance(value, list):
        result = len(value)  # Expected hint: result: int
    else:
        result = None  # Expected hint: result: None

    return result  # Expected hint: return type: int | str | None


def handle_optional(data):
    """Handle optional data."""
    if data is None:
        default = "default"  # Expected hint: default: str
        return default

    processed = data.strip()  # Expected hint: processed: str (if data: str)
    return processed


def union_operations(value):
    """Perform operations on union types."""
    # Type narrowing with isinstance
    if isinstance(value, (int, float)):
        doubled = value * 2  # Expected hint: doubled: int | float
        return doubled

    if isinstance(value, str):
        length = len(value)  # Expected hint: length: int
        return length

    return 0


def multiple_union(x):
    """Handle multiple union branches."""
    match x:
        case int():
            result = x + 1  # Expected hint: result: int
        case str():
            result = len(x)  # Expected hint: result: int
        case list():
            result = sum(x) if x else 0  # Expected hint: result: int
        case _:
            result = -1  # Expected hint: result: int

    return result  # Expected hint: return type: int


# =============================================================================
# LITERAL TYPES
# =============================================================================

type Status = Literal["pending", "processing", "completed", "failed"]
type Direction = Literal["north", "south", "east", "west"]
type LogLevel = Literal["debug", "info", "warning", "error", "critical"]


def set_status(status):
    """Set status with literal validation."""
    valid_statuses = {
        "pending",
        "processing",
        "completed",
        "failed",
    }  # Expected hint: valid_statuses: set

    if status in valid_statuses:
        current = status  # Expected hint: current: str (from status)
        return current

    return "pending"


def get_log_level():
    """Get log level."""
    level = "info"  # Expected hint: level: str
    return level


def direction_to_degrees(direction):
    """Convert direction to degrees."""
    mapping = {  # Expected hint: mapping: dict
        "north": 0,
        "east": 90,
        "south": 180,
        "west": 270,
    }

    degrees = mapping.get(direction, 0)  # Expected hint: degrees: int
    return degrees


# =============================================================================
# TYPEDDICT
# =============================================================================


class UserDict(TypedDict):
    """User dictionary with required fields."""

    id: int
    name: str
    email: str


class ExtendedUserDict(TypedDict):
    """Extended user with optional fields."""

    id: int
    name: str
    email: str
    age: NotRequired[int]
    bio: NotRequired[str]
    verified: NotRequired[bool]


class ConfigDict(TypedDict, total=False):
    """Configuration dictionary (all optional)."""

    debug: bool
    timeout: float
    max_retries: int
    log_level: str


def create_user(user_id, name, email):
    """Create a user dictionary."""
    user = {  # Expected hint: user: dict
        "id": user_id,
        "name": name,
        "email": email,
    }
    return user


def update_user(user, **updates):
    """Update user dictionary."""
    updated = user.copy()  # Expected hint: updated: dict
    updated.update(updates)
    return updated


def get_config():
    """Get configuration dictionary."""
    config = {  # Expected hint: config: dict
        "debug": True,
        "timeout": 30.0,
        "max_retries": 3,
    }
    return config


# =============================================================================
# PROTOCOLS
# =============================================================================


class Comparable(Protocol):
    """Protocol for comparable objects."""

    def __lt__(self, other: Any) -> bool: ...

    def __le__(self, other: Any) -> bool: ...


class Drawable(Protocol):
    """Protocol for drawable objects."""

    def draw(self) -> str: ...

    def get_bounds(self) -> tuple[int, int, int, int]: ...


class Sized(Protocol):
    """Protocol for sized objects."""

    def __len__(self) -> int: ...


def compare_items(a, b):
    """Compare two comparable items."""
    if hasattr(a, "__lt__"):
        is_less = a < b  # Expected hint: is_less: bool
        return is_less
    return False


def draw_object(obj):
    """Draw an object if it has draw method."""
    if hasattr(obj, "draw"):
        result = obj.draw()  # Expected hint: result: Any
        return result
    return "No draw method"


def get_size(obj):
    """Get size of object."""
    if hasattr(obj, "__len__"):
        size = len(obj)  # Expected hint: size: int
        return size
    return 0


# =============================================================================
# GENERICS WITH TYPE PARAMETERS (PEP 695)
# =============================================================================


def identity[T](value: T) -> T:
    """Generic identity function."""
    return value


def first[T](items: list[T]) -> T | None:
    """Get first item from list."""
    if items:
        item = items[0]  # Expected hint: item: T
        return item
    return None


def last[T](items: list[T]) -> T | None:
    """Get last item from list."""
    if items:
        item = items[-1]  # Expected hint: item: T
        return item
    return None


def reverse[T](items: list[T]) -> list[T]:
    """Reverse a list."""
    reversed_list = items[::-1]  # Expected hint: reversed_list: list[T]
    return reversed_list


def pair[T, U](first: T, second: U) -> tuple[T, U]:
    """Create a pair."""
    result = (first, second)  # Expected hint: result: tuple[T, U]
    return result


def swap[T, U](pair_tuple: tuple[T, U]) -> tuple[U, T]:
    """Swap pair elements."""
    a, b = pair_tuple  # Expected hint: a: T, b: U
    swapped = (b, a)  # Expected hint: swapped: tuple[U, T]
    return swapped


class Container[T]:
    """Generic container class."""

    def __init__(self):
        self._items = []  # Expected hint: self._items: list

    def add(self, item: T):
        """Add item to container."""
        self._items.append(item)
        count = len(self._items)  # Expected hint: count: int
        return count

    def get(self, index: int) -> T | None:
        """Get item by index."""
        if 0 <= index < len(self._items):
            item = self._items[index]  # Expected hint: item: T
            return item
        return None

    def all(self) -> list[T]:
        """Get all items."""
        return self._items.copy()


class Pair[T, U]:
    """Generic pair class."""

    def __init__(self, first: T, second: U):
        self.first = first  # Expected hint: self.first: T
        self.second = second  # Expected hint: self.second: U

    def swap(self) -> Pair[U, T]:
        """Swap pair elements."""
        swapped = Pair(self.second, self.first)  # Expected hint: swapped: Pair[U, T]
        return swapped

    def to_tuple(self) -> tuple[T, U]:
        """Convert to tuple."""
        result = (self.first, self.second)  # Expected hint: result: tuple[T, U]
        return result


# =============================================================================
# TYPEVAR WITH CONSTRAINTS
# =============================================================================

T_Number = TypeVar("T_Number", int, float)
T_Str = TypeVar("T_Str", bound=str)


def add_numbers(a, b):
    """Add two numbers (int or float)."""
    result = a + b  # Expected hint: result: int | float
    return result


def multiply_numbers(a, b):
    """Multiply two numbers."""
    product = a * b  # Expected hint: product: int | float
    return product


def process_string(text):
    """Process string or subclass."""
    upper = text.upper()  # Expected hint: upper: str
    stripped = upper.strip()  # Expected hint: stripped: str
    return stripped


# =============================================================================
# PATTERN MATCHING (Python 3.10+)
# =============================================================================


def classify_value(value):
    """Classify value using pattern matching."""
    match value:
        case int(x) if x > 0:
            result = f"positive: {x}"  # Expected hint: result: str
        case int(x) if x < 0:
            result = f"negative: {x}"  # Expected hint: result: str
        case int():
            result = "zero"  # Expected hint: result: str
        case str(s):
            result = f"string: {s}"  # Expected hint: result: str
        case []:
            result = "empty list"  # Expected hint: result: str
        case [x]:
            result = f"singleton: {x}"  # Expected hint: result: str
        case [x, y]:
            result = f"pair: {x}, {y}"  # Expected hint: result: str
        case [*rest]:
            result = f"list of {len(rest)} items"  # Expected hint: result: str
        case _:
            result = "unknown"  # Expected hint: result: str

    return result


def process_point(point):
    """Process point with pattern matching."""
    match point:
        case (0, 0):
            description = "origin"  # Expected hint: description: str
        case (0, y):
            description = f"y-axis at {y}"  # Expected hint: description: str
        case (x, 0):
            description = f"x-axis at {x}"  # Expected hint: description: str
        case (x, y):
            description = f"point at ({x}, {y})"  # Expected hint: description: str
        case _:
            description = "invalid point"  # Expected hint: description: str

    return description


def process_command(command):
    """Process command with pattern matching."""
    match command:
        case {"action": "create", "name": name}:
            result = f"Creating {name}"  # Expected hint: result: str
        case {"action": "delete", "id": obj_id}:
            result = f"Deleting {obj_id}"  # Expected hint: result: str
        case {"action": "update", "id": obj_id, "data": data}:
            result = f"Updating {obj_id} with {data}"  # Expected hint: result: str
        case {"action": action}:
            result = f"Unknown action: {action}"  # Expected hint: result: str
        case _:
            result = "Invalid command"  # Expected hint: result: str

    return result


# =============================================================================
# RECURSIVE TYPES
# =============================================================================


def sum_nested(data):
    """Sum values in nested structure."""
    total = 0  # Expected hint: total: int

    if isinstance(data, int):
        return data
    elif isinstance(data, list):
        for item in data:
            value = sum_nested(item)  # Expected hint: value: int
            total += value

    return total


def flatten_nested(data):
    """Flatten nested list structure."""
    result = []  # Expected hint: result: list

    if not isinstance(data, list):
        return [data]

    for item in data:
        flattened = flatten_nested(item)  # Expected hint: flattened: list
        result.extend(flattened)

    return result


def tree_depth(node):
    """Calculate tree depth."""
    if node is None:
        return 0

    value, children = node  # Expected hint: value: Any, children: list

    if not children:
        return 1

    max_depth = 0  # Expected hint: max_depth: int
    for child in children:
        depth = tree_depth(child)  # Expected hint: depth: int
        if depth > max_depth:
            max_depth = depth

    return max_depth + 1


# =============================================================================
# NEVER TYPE
# =============================================================================


def assert_never(value: Never) -> Never:
    """Assert that code is unreachable."""
    raise AssertionError(f"Unexpected value: {value}")


def exhaustive_check(status):
    """Demonstrate exhaustive checking."""
    if status == "pending":
        result = "Waiting"  # Expected hint: result: str
    elif status == "completed":
        result = "Done"  # Expected hint: result: str
    elif status == "failed":
        result = "Error"  # Expected hint: result: str
    else:
        # This should be unreachable if all cases covered
        result = f"Unknown status: {status}"  # Expected hint: result: str

    return result


# =============================================================================
# TYPE ALIASES IN PRACTICE
# =============================================================================


def create_matrix(rows, cols, default=0):
    """Create a matrix with default values."""
    matrix = [
        [default for _ in range(cols)] for _ in range(rows)
    ]  # Expected hint: matrix: list
    return matrix


def add_matrices(a, b):
    """Add two matrices."""
    if len(a) != len(b) or len(a[0]) != len(b[0]):
        return None

    rows = len(a)  # Expected hint: rows: int
    cols = len(a[0])  # Expected hint: cols: int

    result = create_matrix(rows, cols)  # Expected hint: result: list

    for i in range(rows):
        for j in range(cols):
            result[i][j] = a[i][j] + b[i][j]

    return result


def transpose_matrix(matrix):
    """Transpose a matrix."""
    if not matrix:
        return []

    rows = len(matrix)  # Expected hint: rows: int
    cols = len(matrix[0])  # Expected hint: cols: int

    transposed = [
        [matrix[i][j] for i in range(rows)] for j in range(cols)
    ]  # Expected hint: transposed: list
    return transposed


# =============================================================================
# COMPLEX TYPE COMPOSITIONS
# =============================================================================


def process_result(result):
    """Process a Result type."""
    success, value, error = (
        result  # Expected hint: success: bool, value: Any, error: str | None
    )

    if success and value is not None:
        processed = str(value)  # Expected hint: processed: str
        return processed
    elif error:
        return f"Error: {error}"
    else:
        return "Unknown error"


def create_success_result(value):
    """Create a success result."""
    result = (True, value, None)  # Expected hint: result: tuple
    return result


def create_error_result(error):
    """Create an error result."""
    result = (False, None, error)  # Expected hint: result: tuple
    return result


# =============================================================================
# TYPE GUARD PATTERNS
# =============================================================================


def is_string_list(value):
    """Check if value is a list of strings."""
    if not isinstance(value, list):
        return False

    return all(isinstance(item, str) for item in value)


def process_string_list(value):
    """Process value if it's a string list."""
    if is_string_list(value):
        # Type narrowed to list of strings
        lengths = [len(s) for s in value]  # Expected hint: lengths: list
        total = sum(lengths)  # Expected hint: total: int
        return total

    return 0


def is_numeric(value):
    """Check if value is numeric."""
    return isinstance(value, (int, float))


def safe_divide(a, b):
    """Safely divide two values."""
    if is_numeric(a) and is_numeric(b) and b != 0:
        result = a / b  # Expected hint: result: float
        return result

    return None


# =============================================================================
# EXAMPLE USAGE
# =============================================================================


def demonstrate_modern_types():
    """Demonstrate modern type features."""
    # Generic functions
    int_id = identity(42)  # Expected hint: int_id: int
    str_id = identity("hello")  # Expected hint: str_id: str

    # Union types
    value1 = process_value(10)  # Expected hint: value1: int | str | None
    value2 = process_value("test")  # Expected hint: value2: int | str | None

    # Pattern matching
    classification = classify_value(42)  # Expected hint: classification: str
    point_desc = process_point((3, 4))  # Expected hint: point_desc: str

    # Generic containers
    int_container = Container[int]()  # Expected hint: int_container: Container[int]
    int_container.add(1)
    int_container.add(2)
    items = int_container.all()  # Expected hint: items: list[int]

    # Type aliases
    matrix1 = create_matrix(3, 3)  # Expected hint: matrix1: list
    matrix2 = create_matrix(3, 3, 1)  # Expected hint: matrix2: list
    sum_matrix = add_matrices(
        matrix1, matrix2
    )  # Expected hint: sum_matrix: list | None

    # Results
    success = create_success_result("data")  # Expected hint: success: tuple
    error = create_error_result("failed")  # Expected hint: error: tuple

    summary = {  # Expected hint: summary: dict
        "int_id": int_id,
        "value1": value1,
        "classification": classification,
        "items_count": len(items),
        "success": success[0],
    }

    return summary


if __name__ == "__main__":
    result = demonstrate_modern_types()  # Expected hint: result: dict
    print(f"Modern types demonstration: {result}")
