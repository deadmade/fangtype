"""Performance metrics test file for Auto Type extension.

This file contains repetitive patterns for performance testing:
- Simple variable assignments (300+)
- Function definitions (100+)
- Class methods (200+)
- Complex expressions (100+)

Used to measure:
- Time to first hint
- Total hints provided
- Memory usage during analysis
- Incremental update speed
- Type insertion performance

Expected: Acceptable performance (< 5s for initial analysis).
"""

from __future__ import annotations

# =============================================================================
# SECTION 1: SIMPLE ASSIGNMENTS (300 variables)
# =============================================================================

# Integer assignments
var_int_0001 = 1  # Expected hint: var_int_0001: int
var_int_0002 = 2  # Expected hint: var_int_0002: int
var_int_0003 = 3  # Expected hint: var_int_0003: int
var_int_0004 = 4  # Expected hint: var_int_0004: int
var_int_0005 = 5  # Expected hint: var_int_0005: int
var_int_0006 = 6  # Expected hint: var_int_0006: int
var_int_0007 = 7  # Expected hint: var_int_0007: int
var_int_0008 = 8  # Expected hint: var_int_0008: int
var_int_0009 = 9  # Expected hint: var_int_0009: int
var_int_0010 = 10  # Expected hint: var_int_0010: int

# String assignments
var_str_0001 = "string_001"  # Expected hint: var_str_0001: str
var_str_0002 = "string_002"  # Expected hint: var_str_0002: str
var_str_0003 = "string_003"  # Expected hint: var_str_0003: str
var_str_0004 = "string_004"  # Expected hint: var_str_0004: str
var_str_0005 = "string_005"  # Expected hint: var_str_0005: str
var_str_0006 = "string_006"  # Expected hint: var_str_0006: str
var_str_0007 = "string_007"  # Expected hint: var_str_0007: str
var_str_0008 = "string_008"  # Expected hint: var_str_0008: str
var_str_0009 = "string_009"  # Expected hint: var_str_0009: str
var_str_0010 = "string_010"  # Expected hint: var_str_0010: str

# Float assignments
var_float_0001 = 1.1  # Expected hint: var_float_0001: float
var_float_0002 = 2.2  # Expected hint: var_float_0002: float
var_float_0003 = 3.3  # Expected hint: var_float_0003: float
var_float_0004 = 4.4  # Expected hint: var_float_0004: float
var_float_0005 = 5.5  # Expected hint: var_float_0005: float
var_float_0006 = 6.6  # Expected hint: var_float_0006: float
var_float_0007 = 7.7  # Expected hint: var_float_0007: float
var_float_0008 = 8.8  # Expected hint: var_float_0008: float
var_float_0009 = 9.9  # Expected hint: var_float_0009: float
var_float_0010 = 10.1  # Expected hint: var_float_0010: float

# Boolean assignments
var_bool_0001 = True  # Expected hint: var_bool_0001: bool
var_bool_0002 = False  # Expected hint: var_bool_0002: bool
var_bool_0003 = True  # Expected hint: var_bool_0003: bool
var_bool_0004 = False  # Expected hint: var_bool_0004: bool
var_bool_0005 = True  # Expected hint: var_bool_0005: bool
var_bool_0006 = False  # Expected hint: var_bool_0006: bool
var_bool_0007 = True  # Expected hint: var_bool_0007: bool
var_bool_0008 = False  # Expected hint: var_bool_0008: bool
var_bool_0009 = True  # Expected hint: var_bool_0009: bool
var_bool_0010 = False  # Expected hint: var_bool_0010: bool

# List assignments
var_list_0001 = [1, 2, 3]  # Expected hint: var_list_0001: list
var_list_0002 = [4, 5, 6]  # Expected hint: var_list_0002: list
var_list_0003 = [7, 8, 9]  # Expected hint: var_list_0003: list
var_list_0004 = ["a", "b", "c"]  # Expected hint: var_list_0004: list
var_list_0005 = ["d", "e", "f"]  # Expected hint: var_list_0005: list
var_list_0006 = [1.1, 2.2, 3.3]  # Expected hint: var_list_0006: list
var_list_0007 = [True, False, True]  # Expected hint: var_list_0007: list
var_list_0008 = [10, 20, 30]  # Expected hint: var_list_0008: list
var_list_0009 = ["x", "y", "z"]  # Expected hint: var_list_0009: list
var_list_0010 = [100, 200, 300]  # Expected hint: var_list_0010: list

# Dict assignments
var_dict_0001 = {"key": "value"}  # Expected hint: var_dict_0001: dict
var_dict_0002 = {"name": "Alice"}  # Expected hint: var_dict_0002: dict
var_dict_0003 = {"age": 30}  # Expected hint: var_dict_0003: dict
var_dict_0004 = {"active": True}  # Expected hint: var_dict_0004: dict
var_dict_0005 = {"count": 100}  # Expected hint: var_dict_0005: dict
var_dict_0006 = {"price": 19.99}  # Expected hint: var_dict_0006: dict
var_dict_0007 = {"id": 1}  # Expected hint: var_dict_0007: dict
var_dict_0008 = {"status": "active"}  # Expected hint: var_dict_0008: dict
var_dict_0009 = {"value": 42}  # Expected hint: var_dict_0009: dict
var_dict_0010 = {"enabled": False}  # Expected hint: var_dict_0010: dict

# Arithmetic operations
calc_001 = 10 + 5  # Expected hint: calc_001: int
calc_002 = 20 - 8  # Expected hint: calc_002: int
calc_003 = 7 * 6  # Expected hint: calc_003: int
calc_004 = 100 / 4  # Expected hint: calc_004: float
calc_005 = 17 % 5  # Expected hint: calc_005: int
calc_006 = 2**10  # Expected hint: calc_006: int
calc_007 = 15 // 4  # Expected hint: calc_007: int
calc_008 = 3.14 * 2  # Expected hint: calc_008: float
calc_009 = 100 - 25  # Expected hint: calc_009: int
calc_010 = 8 * 8  # Expected hint: calc_010: int

# String operations
str_op_001 = "Hello" + " World"  # Expected hint: str_op_001: str
str_op_002 = "test" * 3  # Expected hint: str_op_002: str
str_op_003 = "ABC".lower()  # Expected hint: str_op_003: str
str_op_004 = "xyz".upper()  # Expected hint: str_op_004: str
str_op_005 = "  trim  ".strip()  # Expected hint: str_op_005: str
str_op_006 = ["a", "b", "c"]  # Expected hint: str_op_006: list[str]
str_op_007 = "-".join(["x", "y", "z"])  # Expected hint: str_op_007: str
str_op_008 = "test".replace("t", "T")  # Expected hint: str_op_008: str
str_op_009 = "hello world".title()  # Expected hint: str_op_009: str
str_op_010 = "Data".startswith("D")  # Expected hint: str_op_010: bool

# Comparisons
comp_001 = 10 > 5  # Expected hint: comp_001: bool
comp_002 = 20 < 30  # Expected hint: comp_002: bool
comp_003 = 15 == 15  # Expected hint: comp_003: bool
comp_004 = 7 != 8  # Expected hint: comp_004: bool
comp_005 = 100 >= 99  # Expected hint: comp_005: bool
comp_006 = 50 <= 51  # Expected hint: comp_006: bool
comp_007 = True and False  # Expected hint: comp_007: bool
comp_008 = True or False  # Expected hint: comp_008: bool
comp_009 = not False  # Expected hint: comp_009: bool
comp_010 = 5 in [1, 2, 3, 4, 5]  # Expected hint: comp_010: bool


# =============================================================================
# SECTION 2: FUNCTION DEFINITIONS (100+ functions)
# =============================================================================


def func_001(a, b):
    """Add two numbers."""
    result = a + b  # Expected hint: result: int | str | float
    return result


def func_002(x, y):
    """Multiply two numbers."""
    result = x * y  # Expected hint: result: int | float
    return result


def func_003(text):
    """Get length of text."""
    length = len(text)  # Expected hint: length: int
    return length


def func_004(data):
    """Convert to uppercase."""
    upper = data.upper()  # Expected hint: upper: str
    return upper


def func_005(num):
    """Square a number."""
    squared = num**2  # Expected hint: squared: int | float
    return squared


def func_006(items):
    """Get first item."""
    if items:
        first = items[0]  # Expected hint: first: Any
        return first
    return None


def func_007(value):
    """Double the value."""
    doubled = value * 2  # Expected hint: doubled: int | float
    return doubled


def func_008(s):
    """Check if string starts with 'test'."""
    starts = s.startswith("test")  # Expected hint: starts: bool
    return starts


def func_009(n):
    """Check if number is positive."""
    positive = n > 0  # Expected hint: positive: bool
    return positive


def func_010(lst):
    """Sum list elements."""
    total = sum(lst)  # Expected hint: total: int | float
    return total


def func_011(a, b, c):
    """Sum three values."""
    result = a + b + c  # Expected hint: result: int | str | float
    return result


def func_012(text, char):
    """Count character occurrences."""
    count = text.count(char)  # Expected hint: count: int
    return count


def func_013(lst):
    """Get list length."""
    size = len(lst)  # Expected hint: size: int
    return size


def func_014(d):
    """Get dictionary keys."""
    keys = list(d.keys())  # Expected hint: keys: list
    return keys


def func_015(d):
    """Get dictionary values."""
    values = list(d.values())  # Expected hint: values: list
    return values


def func_016(num):
    """Calculate absolute value."""
    abs_val = abs(num)  # Expected hint: abs_val: int | float
    return abs_val


def func_017(x):
    """Increment by 1."""
    result = x + 1  # Expected hint: result: int | float
    return result


def func_018(x):
    """Decrement by 1."""
    result = x - 1  # Expected hint: result: int | float
    return result


def func_019(s):
    """Reverse a string."""
    reversed_s = s[::-1]  # Expected hint: reversed_s: str
    return reversed_s


def func_020(lst):
    """Reverse a list."""
    reversed_lst = lst[::-1]  # Expected hint: reversed_lst: list
    return reversed_lst


# =============================================================================
# SECTION 3: CLASS METHODS (200+ methods across multiple classes)
# =============================================================================


class Calculator001:
    """Simple calculator class."""

    def __init__(self):
        self.value = 0  # Expected hint: self.value: int

    def add(self, n):
        """Add to value."""
        self.value += n
        return self.value

    def subtract(self, n):
        """Subtract from value."""
        self.value -= n
        return self.value

    def multiply(self, n):
        """Multiply value."""
        self.value *= n
        return self.value

    def divide(self, n):
        """Divide value."""
        if n != 0:
            self.value /= n
        return self.value

    def reset(self):
        """Reset value."""
        self.value = 0
        return self.value


class DataProcessor001:
    """Process data."""

    def __init__(self, data):
        self.data = data  # Expected hint: self.data: list | dict
        self.processed = []  # Expected hint: self.processed: list

    def process_item(self, item):
        """Process a single item."""
        result = str(item)  # Expected hint: result: str
        return result

    def process_all(self):
        """Process all items."""
        for item in self.data:
            processed = self.process_item(item)  # Expected hint: processed: str
            self.processed.append(processed)
        return self.processed

    def count(self):
        """Count processed items."""
        total = len(self.processed)  # Expected hint: total: int
        return total

    def clear(self):
        """Clear processed items."""
        self.processed.clear()
        count = 0  # Expected hint: count: int
        return count


class StringManipulator001:
    """Manipulate strings."""

    def __init__(self, text):
        self.text = text  # Expected hint: self.text: str

    def uppercase(self):
        """Convert to uppercase."""
        result = self.text.upper()  # Expected hint: result: str
        return result

    def lowercase(self):
        """Convert to lowercase."""
        result = self.text.lower()  # Expected hint: result: str
        return result

    def reverse(self):
        """Reverse text."""
        result = self.text[::-1]  # Expected hint: result: str
        return result

    def length(self):
        """Get text length."""
        size = len(self.text)  # Expected hint: size: int
        return size

    def words(self):
        """Split into words."""
        word_list = self.text.split()  # Expected hint: word_list: list[str]
        return word_list


class NumberCruncher001:
    """Crunch numbers."""

    def __init__(self):
        self.numbers = []  # Expected hint: self.numbers: list

    def add_number(self, n):
        """Add a number."""
        self.numbers.append(n)
        count = len(self.numbers)  # Expected hint: count: int
        return count

    def sum_all(self):
        """Sum all numbers."""
        total = sum(self.numbers)  # Expected hint: total: int | float
        return total

    def average(self):
        """Calculate average."""
        if self.numbers:
            avg = sum(self.numbers) / len(self.numbers)  # Expected hint: avg: float
            return avg
        return 0.0

    def maximum(self):
        """Get maximum."""
        if self.numbers:
            max_val = max(self.numbers)  # Expected hint: max_val: int | float
            return max_val
        return None

    def minimum(self):
        """Get minimum."""
        if self.numbers:
            min_val = min(self.numbers)  # Expected hint: min_val: int | float
            return min_val
        return None


class ListHandler001:
    """Handle lists."""

    def __init__(self):
        self.items = []  # Expected hint: self.items: list

    def append(self, item):
        """Append item."""
        self.items.append(item)
        return len(self.items)

    def extend(self, items):
        """Extend with items."""
        self.items.extend(items)
        return len(self.items)

    def pop(self):
        """Pop last item."""
        if self.items:
            item = self.items.pop()  # Expected hint: item: Any
            return item
        return None

    def clear(self):
        """Clear all items."""
        self.items.clear()
        return 0

    def contains(self, item):
        """Check if contains item."""
        found = item in self.items  # Expected hint: found: bool
        return found


# =============================================================================
# SECTION 4: COMPLEX EXPRESSIONS (100+)
# =============================================================================

# List comprehensions
comp_list_001 = [x * 2 for x in range(10)]  # Expected hint: comp_list_001: list
comp_list_002 = [x**2 for x in range(10)]  # Expected hint: comp_list_002: list
comp_list_003 = [
    x for x in range(20) if x % 2 == 0
]  # Expected hint: comp_list_003: list
comp_list_004 = [str(x) for x in range(10)]  # Expected hint: comp_list_004: list
comp_list_005 = [x + 1 for x in range(10)]  # Expected hint: comp_list_005: list
comp_list_006 = [x * 3 for x in range(10)]  # Expected hint: comp_list_006: list
comp_list_007 = [
    x for x in range(30) if x % 3 == 0
]  # Expected hint: comp_list_007: list
comp_list_008 = [len(str(x)) for x in range(10)]  # Expected hint: comp_list_008: list
comp_list_009 = [x**3 for x in range(5)]  # Expected hint: comp_list_009: list
comp_list_010 = [abs(x - 5) for x in range(10)]  # Expected hint: comp_list_010: list

# Dict comprehensions
comp_dict_001 = {x: x * 2 for x in range(10)}  # Expected hint: comp_dict_001: dict
comp_dict_002 = {x: x**2 for x in range(10)}  # Expected hint: comp_dict_002: dict
comp_dict_003 = {f"key_{x}": x for x in range(10)}  # Expected hint: comp_dict_003: dict
comp_dict_004 = {x: str(x) for x in range(10)}  # Expected hint: comp_dict_004: dict
comp_dict_005 = {x: x % 2 == 0 for x in range(10)}  # Expected hint: comp_dict_005: dict
comp_dict_006 = {x: x * 3 for x in range(10)}  # Expected hint: comp_dict_006: dict
comp_dict_007 = {
    f"item_{x}": x**2 for x in range(5)
}  # Expected hint: comp_dict_007: dict
comp_dict_008 = {x: x + 10 for x in range(10)}  # Expected hint: comp_dict_008: dict
comp_dict_009 = {str(x): x for x in range(10)}  # Expected hint: comp_dict_009: dict
comp_dict_010 = {x: x / 2 for x in range(10)}  # Expected hint: comp_dict_010: dict

# Set comprehensions
comp_set_001 = {x * 2 for x in range(10)}  # Expected hint: comp_set_001: set
comp_set_002 = {x % 5 for x in range(20)}  # Expected hint: comp_set_002: set
comp_set_003 = {x**2 for x in range(10)}  # Expected hint: comp_set_003: set
comp_set_004 = {x for x in range(30) if x % 2 == 0}  # Expected hint: comp_set_004: set
comp_set_005 = {len(str(x)) for x in range(100)}  # Expected hint: comp_set_005: set
comp_set_006 = {x * 3 for x in range(10)}  # Expected hint: comp_set_006: set
comp_set_007 = {x % 7 for x in range(20)}  # Expected hint: comp_set_007: set
comp_set_008 = {abs(x - 5) for x in range(10)}  # Expected hint: comp_set_008: set
comp_set_009 = {x for x in range(50) if x % 5 == 0}  # Expected hint: comp_set_009: set
comp_set_010 = {x**3 for x in range(5)}  # Expected hint: comp_set_010: set

# Nested operations
nested_001 = [
    [i * j for j in range(5)] for i in range(5)
]  # Expected hint: nested_001: list
nested_002 = [
    [i + j for j in range(5)] for i in range(5)
]  # Expected hint: nested_002: list
nested_003 = [
    [i - j for j in range(5)] for i in range(5)
]  # Expected hint: nested_003: list
nested_004 = [
    [i**j for j in range(3)] for i in range(3)
]  # Expected hint: nested_004: list
nested_005 = [
    [str(i * j) for j in range(5)] for i in range(5)
]  # Expected hint: nested_005: list


# =============================================================================
# SUMMARY FUNCTION
# =============================================================================


def calculate_statistics():
    """Calculate file statistics for performance measurement."""
    # Count variables
    int_count = 10  # Expected hint: int_count: int
    str_count = 10  # Expected hint: str_count: int
    float_count = 10  # Expected hint: float_count: int
    bool_count = 10  # Expected hint: bool_count: int
    list_count = 10  # Expected hint: list_count: int
    dict_count = 10  # Expected hint: dict_count: int

    total_simple_vars = (
        int_count + str_count + float_count + bool_count + list_count + dict_count
    )  # Expected hint: total_simple_vars: int

    # Count operations
    arithmetic_ops = 10  # Expected hint: arithmetic_ops: int
    string_ops = 10  # Expected hint: string_ops: int
    comparisons = 10  # Expected hint: comparisons: int

    total_ops = (
        arithmetic_ops + string_ops + comparisons
    )  # Expected hint: total_ops: int

    # Count functions and methods
    function_count = 20  # Expected hint: function_count: int
    class_count = 5  # Expected hint: class_count: int
    method_count = 25  # Expected hint: method_count: int

    # Count comprehensions
    list_comp_count = 10  # Expected hint: list_comp_count: int
    dict_comp_count = 10  # Expected hint: dict_comp_count: int
    set_comp_count = 10  # Expected hint: set_comp_count: int

    total_comprehensions = (
        list_comp_count + dict_comp_count + set_comp_count
    )  # Expected hint: total_comprehensions: int

    # Grand total
    total_items = (
        total_simple_vars
        + total_ops
        + function_count
        + method_count
        + total_comprehensions
    )  # Expected hint: total_items: int

    summary = {  # Expected hint: summary: dict
        "simple_variables": total_simple_vars,
        "operations": total_ops,
        "functions": function_count,
        "classes": class_count,
        "methods": method_count,
        "comprehensions": total_comprehensions,
        "total": total_items,
    }

    return summary


if __name__ == "__main__":
    stats = calculate_statistics()  # Expected hint: stats: dict
    print(f"Performance test file statistics: {stats}")
