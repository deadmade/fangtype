"""Edge cases and unusual patterns for testing Auto Type extension robustness.

Tests boundary conditions, unusual patterns, and error handling:
- Very long identifiers and lines
- Deeply nested expressions
- Complex lambda expressions
- Walrus operator (:=)
- Multiple assignment forms
- Exception handling branches
- Dynamic attribute access
- Type narrowing in complex conditions
- Unicode variable names
- Edge case operators and expressions

Expected: Robust handling without crashes or errors.
"""

from __future__ import annotations

import re
from contextlib import suppress

# =============================================================================
# LONG IDENTIFIERS
# =============================================================================

this_is_an_extremely_long_variable_name_that_tests_the_extension_handling_of_very_long_identifiers_in_python_code = 42  # Expected hint: int
another_very_long_variable_name_with_many_underscores_to_simulate_real_world_verbose_naming_conventions = "test"  # Expected hint: str


def function_with_very_long_name_that_might_cause_issues_with_line_wrapping_or_display():
    """Function with extremely long name."""
    result = 100  # Expected hint: result: int
    return result


# =============================================================================
# DEEPLY NESTED EXPRESSIONS
# =============================================================================


def deeply_nested_arithmetic():
    """Test deeply nested arithmetic operations."""
    result = (((((1 + 2) * 3) - 4) / 5) ** 2) + 10  # Expected hint: result: float
    return result


def nested_list_comprehensions():
    """Deeply nested list comprehensions."""
    matrix = [
        [[i + j + k for k in range(3)] for j in range(3)] for i in range(3)
    ]  # Expected hint: matrix: list
    flattened = [
        item for sublist1 in matrix for sublist2 in sublist1 for item in sublist2
    ]  # Expected hint: flattened: list
    return matrix, flattened


def nested_dict_access():
    """Deeply nested dictionary access."""
    data = {"a": {"b": {"c": {"d": {"e": 42}}}}}  # Expected hint: data: dict
    value = data["a"]["b"]["c"]["d"]["e"]  # Expected hint: value: int
    return value


def nested_function_calls():
    """Deeply nested function calls."""
    result = str(int(float(str(int(float(str(42)))))))  # Expected hint: result: str
    return result


# =============================================================================
# COMPLEX LAMBDA EXPRESSIONS
# =============================================================================

complex_lambda_1 = lambda x, y, z: (
    (x + y) * z if z > 0 else (x - y) / (z or 1)
)  # Expected hint: Callable

complex_lambda_2 = lambda data: {  # Expected hint: Callable
    k: [item * 2 for item in v if item > 0] for k, v in data.items() if len(v) > 0
}

complex_lambda_3 = lambda *args, **kwargs: (
    sum(args) + sum(kwargs.values())
)  # Expected hint: Callable

nested_lambda = lambda x: lambda y: lambda z: x + y + z  # Expected hint: Callable


def use_complex_lambdas():
    """Use complex lambda expressions."""
    result1 = complex_lambda_1(10, 5, 2)  # Expected hint: result1: int | float
    result2 = complex_lambda_2(
        {"a": [1, 2, 3], "b": [4, 5]}
    )  # Expected hint: result2: dict
    result3 = complex_lambda_3(1, 2, 3, x=4, y=5)  # Expected hint: result3: int

    # Use nested lambda
    add_10 = nested_lambda(10)  # Expected hint: add_10: Callable
    add_10_20 = add_10(20)  # Expected hint: add_10_20: Callable
    result4 = add_10_20(30)  # Expected hint: result4: int

    return result1, result2, result3, result4


# =============================================================================
# WALRUS OPERATOR (:=)
# =============================================================================


def walrus_in_if():
    """Walrus operator in if statement."""
    data = "test string"  # Expected hint: data: str

    if (length := len(data)) > 5:  # Expected hint: length: int
        result = f"Long string: {length}"  # Expected hint: result: str
    else:
        result = "Short string"  # Expected hint: result: str

    return result


def walrus_in_while():
    """Walrus operator in while loop."""
    items = [1, 2, 3, 4, 5]  # Expected hint: items: list
    results = []  # Expected hint: results: list

    while (
        item := items.pop() if items else None
    ) is not None:  # Expected hint: item: int | None
        doubled = item * 2  # Expected hint: doubled: int
        results.append(doubled)

    return results


def walrus_in_comprehension():
    """Walrus operator in list comprehension."""
    data = [1, 2, 3, 4, 5]  # Expected hint: data: list
    results = [
        (x, squared) for x in data if (squared := x**2) > 5
    ]  # Expected hint: results: list
    return results


def walrus_with_regex():
    """Walrus operator with regex matching."""
    text = "The answer is 42 and the question is unknown."  # Expected hint: text: str
    pattern = re.compile(r"\d+")  # Expected hint: pattern: Pattern[str]

    if match := pattern.search(text):  # Expected hint: match: Match[str] | None
        found = match.group()  # Expected hint: found: str
        number = int(found)  # Expected hint: number: int
        return number

    return None


# =============================================================================
# MULTIPLE ASSIGNMENT FORMS
# =============================================================================


def tuple_unpacking():
    """Various tuple unpacking patterns."""
    # Simple unpacking
    a, b = 1, 2  # Expected hint: a: int, b: int

    # With starred expression
    first, *rest, last = [
        1,
        2,
        3,
        4,
        5,
    ]  # Expected hint: first: int, rest: list, last: int

    # Nested unpacking
    (x, y), (z, w) = ((1, 2), (3, 4))  # Expected hint: x: int, y: int, z: int, w: int

    # Swapping
    a, b = b, a  # Expected hint: a: int, b: int

    # Multiple assignment
    a = b = c = 10  # Expected hint: a: int, b: int, c: int

    return first, rest, last, x, y, z, w


def list_unpacking():
    """List unpacking patterns."""
    # List unpacking
    [a, b, c] = [1, 2, 3]  # Expected hint: a: int, b: int, c: int

    # With starred
    [first, *middle, last] = list(
        range(10)
    )  # Expected hint: first: int, middle: list, last: int

    return first, middle, last


def chained_assignment():
    """Chained assignment patterns."""
    x = y = z = 0  # Expected hint: x: int, y: int, z: int

    # With operations
    a = b = c = [1, 2, 3]  # Expected hint: a: list, b: list, c: list

    # With different types (last one wins)
    m = n = 5  # Expected hint: m: int, n: int
    m = "changed"  # Expected hint: m: str

    return x, y, z, m, n


# =============================================================================
# EXCEPTION HANDLING
# =============================================================================


def multiple_except_clauses():
    """Multiple exception types and handling."""
    result = None  # Expected hint: result: None

    try:
        value = int("not a number")  # Expected hint: value: int
        result = value * 2  # Expected hint: result: int
    except ValueError as e:
        error_msg = str(e)  # Expected hint: error_msg: str
        result = -1  # Expected hint: result: int
    except TypeError:
        result = -2  # Expected hint: result: int
    except (KeyError, IndexError):
        result = -3  # Expected hint: result: int
    except Exception:
        result = -99  # Expected hint: result: int
    else:
        result = 0  # Expected hint: result: int
    finally:
        cleanup = True  # Expected hint: cleanup: bool

    return result


def nested_try_except():
    """Nested try-except blocks."""
    outer_result = None  # Expected hint: outer_result: None

    try:
        try:
            value = 10 / 0  # Expected hint: value: float
        except ZeroDivisionError:
            inner_result = "Inner catch"  # Expected hint: inner_result: str
            raise ValueError("Reraised")
    except ValueError:
        outer_result = "Outer catch"  # Expected hint: outer_result: str

    return outer_result


def exception_with_type_narrowing():
    """Exception handling with type narrowing."""
    data = {"key": "value"}  # Expected hint: data: dict

    try:
        value = data["missing_key"]  # Expected hint: value: str
    except KeyError:
        value = "default"  # Expected hint: value: str

    return value


# =============================================================================
# DYNAMIC ATTRIBUTE ACCESS
# =============================================================================


class DynamicClass:
    """Class with dynamic attributes."""

    def __init__(self):
        self._data = {}  # Expected hint: self._data: dict

    def __getattr__(self, name):
        """Dynamic attribute getter."""
        value = self._data.get(name, None)  # Expected hint: value: Any
        return value

    def __setattr__(self, name, value):
        """Dynamic attribute setter."""
        if name.startswith("_"):
            super().__setattr__(name, value)
        else:
            if hasattr(self, "_data"):
                self._data[name] = value


def use_dynamic_class():
    """Use dynamic class."""
    obj = DynamicClass()  # Expected hint: obj: DynamicClass
    obj.dynamic_attr = 42  # Dynamic attribute
    value = obj.dynamic_attr  # Expected hint: value: Any
    return value


# =============================================================================
# CONTEXT MANAGERS
# =============================================================================


def multiple_context_managers():
    """Multiple context managers in one statement."""
    with open("/tmp/file1.txt", "w") as f1, open("/tmp/file2.txt", "w") as f2:
        data1 = "content1"  # Expected hint: data1: str
        data2 = "content2"  # Expected hint: data2: str
        f1.write(data1)
        f2.write(data2)
        combined = data1 + data2  # Expected hint: combined: str

    return combined


def nested_context_managers():
    """Nested context managers."""
    with suppress(FileNotFoundError), open("/tmp/test.txt") as f:
        content = f.read()  # Expected hint: content: str
        lines = content.splitlines()  # Expected hint: lines: list
        return lines
    return []


# =============================================================================
# TYPE NARROWING
# =============================================================================


def complex_type_narrowing(value):
    """Complex type narrowing patterns."""
    if value is None:
        result = "none"  # Expected hint: result: str
    elif isinstance(value, int):
        if value > 0:
            result = value * 2  # Expected hint: result: int
        elif value < 0:
            result = abs(value)  # Expected hint: result: int
        else:
            result = 0  # Expected hint: result: int
    elif isinstance(value, str):
        if len(value) > 0:
            result = value.upper()  # Expected hint: result: str
        else:
            result = "empty"  # Expected hint: result: str
    elif isinstance(value, list):
        if len(value) > 0:
            result = len(value)  # Expected hint: result: int
        else:
            result = 0  # Expected hint: result: int
    else:
        result = str(value)  # Expected hint: result: str

    return result


def type_narrowing_with_and(value1, value2):
    """Type narrowing with logical AND."""
    if isinstance(value1, int) and isinstance(value2, int):
        sum_result = value1 + value2  # Expected hint: sum_result: int
        return sum_result
    elif isinstance(value1, str) and isinstance(value2, str):
        concat = value1 + value2  # Expected hint: concat: str
        return concat
    else:
        return None


def type_narrowing_with_or(value):
    """Type narrowing with logical OR."""
    if isinstance(value, int) or isinstance(value, float):
        doubled = value * 2  # Expected hint: doubled: int | float
        return doubled

    return None


# =============================================================================
# UNICODE AND SPECIAL CHARACTERS
# =============================================================================

π = 3.14159  # Expected hint: π: float
τ = 2 * π  # Expected hint: τ: float
café = "coffee shop"  # Expected hint: café: str
日本 = "Japan"  # Expected hint: 日本: str
münchen = "Munich"  # Expected hint: münchen: str


def unicode_function_name_函数():
    """Function with unicode name."""
    result = 42  # Expected hint: result: int
    return result


# =============================================================================
# UNUSUAL OPERATORS AND EXPRESSIONS
# =============================================================================


def matrix_multiplication_operator():
    """Test @ operator (matrix multiplication)."""

    # Simulate matrix multiplication with lists
    class Matrix:
        def __init__(self, data):
            self.data = data

        def __matmul__(self, other):
            # Simplified matrix multiplication
            result = Matrix([[0, 0], [0, 0]])  # Expected hint: result: Matrix
            return result

    m1 = Matrix([[1, 2], [3, 4]])  # Expected hint: m1: Matrix
    m2 = Matrix([[5, 6], [7, 8]])  # Expected hint: m2: Matrix
    m3 = m1 @ m2  # Expected hint: m3: Matrix

    return m3


def floor_division_and_modulo():
    """Test floor division and modulo."""
    a = 17  # Expected hint: a: int
    b = 5  # Expected hint: b: int

    quotient = a // b  # Expected hint: quotient: int
    remainder = a % b  # Expected hint: remainder: int
    divmod_result = divmod(a, b)  # Expected hint: divmod_result: tuple[int, int]

    return quotient, remainder, divmod_result


def bitwise_operators():
    """Test bitwise operators."""
    a = 0b1010  # Expected hint: a: int
    b = 0b1100  # Expected hint: b: int

    and_result = a & b  # Expected hint: and_result: int
    or_result = a | b  # Expected hint: or_result: int
    xor_result = a ^ b  # Expected hint: xor_result: int
    not_result = ~a  # Expected hint: not_result: int
    left_shift = a << 2  # Expected hint: left_shift: int
    right_shift = a >> 1  # Expected hint: right_shift: int

    return and_result, or_result, xor_result, not_result, left_shift, right_shift


def comparison_chaining():
    """Test comparison chaining."""
    x = 5  # Expected hint: x: int

    result1 = 0 < x < 10  # Expected hint: result1: bool
    result2 = 1 <= x <= 10  # Expected hint: result2: bool
    result3 = 10 > x > 0  # Expected hint: result3: bool
    result4 = 1 < x < 5 < 10  # Expected hint: result4: bool

    return result1, result2, result3, result4


# =============================================================================
# VERY LONG LINES
# =============================================================================

very_long_single_line = {
    "key1": "value1",
    "key2": "value2",
    "key3": "value3",
    "key4": "value4",
    "key5": "value5",
    "key6": "value6",
    "key7": "value7",
    "key8": "value8",
    "key9": "value9",
    "key10": "value10",
}  # Expected hint: dict

very_long_expression = (1 + 2 + 3 + 4 + 5 + 6 + 7 + 8 + 9 + 10) * (
    11 + 12 + 13 + 14 + 15
) / (16 + 17 + 18 + 19 + 20) - (21 + 22 + 23 + 24 + 25)  # Expected hint: float


# =============================================================================
# EDGE CASE COLLECTIONS
# =============================================================================


def empty_collections():
    """Test empty collections."""
    empty_list = []  # Expected hint: empty_list: list
    empty_dict = {}  # Expected hint: empty_dict: dict
    empty_set = set()  # Expected hint: empty_set: set
    empty_tuple = ()  # Expected hint: empty_tuple: tuple

    return empty_list, empty_dict, empty_set, empty_tuple


def single_element_collections():
    """Test single-element collections."""
    single_list = [1]  # Expected hint: single_list: list
    single_dict = {"key": "value"}  # Expected hint: single_dict: dict
    single_set = {1}  # Expected hint: single_set: set
    single_tuple = (1,)  # Expected hint: single_tuple: tuple

    return single_list, single_dict, single_set, single_tuple


def nested_empty_collections():
    """Test nested empty collections."""
    nested = [[], {}, set(), ()]  # Expected hint: nested: list
    deeply_nested = [[[[]]]]  # Expected hint: deeply_nested: list

    return nested, deeply_nested


# =============================================================================
# ELLIPSIS AND PASS
# =============================================================================


def function_with_ellipsis():
    """Function using ellipsis."""
    ...


def function_with_pass():
    """Function using pass."""
    pass


def function_with_notimplemented():
    """Function returning NotImplemented."""
    return NotImplemented


# =============================================================================
# COMPLEX SLICING
# =============================================================================


def complex_slicing():
    """Test complex slicing operations."""
    data = list(range(20))  # Expected hint: data: list

    # Various slices
    slice1 = data[::2]  # Expected hint: slice1: list
    slice2 = data[::-1]  # Expected hint: slice2: list
    slice3 = data[5:15:3]  # Expected hint: slice3: list
    slice4 = data[:-5]  # Expected hint: slice4: list
    slice5 = data[-10:]  # Expected hint: slice5: list

    return slice1, slice2, slice3, slice4, slice5


# =============================================================================
# EXAMPLE USAGE
# =============================================================================


def demonstrate_edge_cases():
    """Demonstrate all edge cases."""
    # Long identifiers
    long_result = function_with_very_long_name_that_might_cause_issues_with_line_wrapping_or_display()  # Expected hint: long_result: int

    # Nested expressions
    nested_result = deeply_nested_arithmetic()  # Expected hint: nested_result: float

    # Walrus operator
    walrus_result = walrus_in_if()  # Expected hint: walrus_result: str

    # Multiple assignment
    unpacking_result = tuple_unpacking()  # Expected hint: unpacking_result: tuple

    # Exception handling
    exception_result = (
        multiple_except_clauses()
    )  # Expected hint: exception_result: int | None

    # Type narrowing
    narrowed = complex_type_narrowing(42)  # Expected hint: narrowed: int | str

    # Unicode
    unicode_result = unicode_function_name_函数()  # Expected hint: unicode_result: int

    # Operators
    bitwise_result = bitwise_operators()  # Expected hint: bitwise_result: tuple

    summary = {  # Expected hint: summary: dict
        "long": long_result,
        "nested": nested_result,
        "walrus": walrus_result,
        "exception": exception_result,
        "unicode": unicode_result,
    }

    return summary


if __name__ == "__main__":
    result = demonstrate_edge_cases()  # Expected hint: result: dict
    this_is_an_extremely_long_variable_name_that_tests_the_extension_handling_of_very_long_identifiers_in_python_code = 42  # Expected hint: int
    print(f"Edge cases: {result}")
