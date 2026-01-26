"""Simple test file to verify Auto Type inlay hints are working.

This file demonstrates the most basic patterns that should show type hints.
Open this file in VSCode and look for ghost text showing inferred types.
"""

# =============================================================================
# MODULE-LEVEL VARIABLES (should show hints)
# =============================================================================

# Basic literals
x = 42  # Should show: x: int
name = "Alice"  # Should show: name: str
pi = 3.14  # Should show: pi: float
is_ready = True  # Should show: is_ready: bool
nothing = None  # Should show: nothing: None

# Collections
items = [1, 2, 3]  # Should show: items: list
data = {"key": "value"}  # Should show: data: dict
unique = {1, 2, 3}  # Should show: unique: set
coords = (10, 20)  # Should show: coords: tuple

# Simple expressions
sum_result = 5 + 10  # Should show: sum_result: int
greeting = "Hello " + "World"  # Should show: greeting: str
comparison = 5 > 3  # Should show: comparison: bool
product = 3 * 4  # Should show: product: int

# =============================================================================
# ARITHMETIC OPERATIONS (NEW - should show hints)
# =============================================================================

# Basic arithmetic with integers
addition = 10 + 5  # Should show: addition: int
subtraction = 10 - 3  # Should show: subtraction: int
multiplication = 7 * 8  # Should show: multiplication: int
division = 20 / 4  # Should show: division: float (always float in Python 3)
floor_div = 20 // 3  # Should show: floor_div: int
modulo = 17 % 5  # Should show: modulo: int
power = 2**10  # Should show: power: int

# Type promotion (int + float → float)
mixed1 = 5 + 3.0  # Should show: mixed1: float
mixed2 = 10 - 2.5  # Should show: mixed2: float
mixed3 = 3 * 1.5  # Should show: mixed3: float
floor_mixed = 10 // 2.0  # Should show: floor_mixed: float

# Float arithmetic
float_add = 2.5 + 3.7  # Should show: float_add: float
float_mult = 1.5 * 2.0  # Should show: float_mult: float

# Boolean arithmetic (bool promotes to int)
bool_math = True + 1  # Should show: bool_math: int
bool_sum = False + False  # Should show: bool_sum: int

# =============================================================================
# STRING OPERATIONS (NEW - should show hints)
# =============================================================================

# String concatenation
full_name = "John" + " " + "Doe"  # Should show: full_name: str
path = "home/" + "user"  # Should show: path: str

# String repetition
repeated = "abc" * 3  # Should show: repeated: str
dashes = "-" * 10  # Should show: dashes: str
reverse_rep = 5 * "xyz"  # Should show: reverse_rep: str (int * str works too)

# =============================================================================
# COLLECTION OPERATIONS (NEW - should show hints)
# =============================================================================

# List operations
list_concat = [1, 2] + [3, 4]  # noqa: RUF005 - Should show: list_concat: list
list_repeat = [0] * 5  # Should show: list_repeat: list
reverse_list = 3 * [1, 2]  # Should show: reverse_list: list

# Tuple operations
tuple_concat = (1, 2) + (3, 4)  # noqa: RUF005 - Should show: tuple_concat: tuple
tuple_repeat = ("a",) * 3  # Should show: tuple_repeat: tuple
reverse_tuple = 2 * (1, 2, 3)  # Should show: reverse_tuple: tuple

# Set operations (bitwise operators on sets)
set_union = {1, 2} | {3, 4}  # Should show: set_union: set
set_intersect = {1, 2, 3} & {2, 3, 4}  # Should show: set_intersect: set
set_symmetric = {1, 2} ^ {2, 3}  # Should show: set_symmetric: set (note: XOR on sets)

# =============================================================================
# BITWISE OPERATIONS (NEW - should show hints)
# =============================================================================

# Bitwise operators on integers
bitwise_and = 12 & 7  # Should show: bitwise_and: int
bitwise_or = 4 | 8  # Should show: bitwise_or: int
bitwise_xor = 15 ^ 9  # Should show: bitwise_xor: int
left_shift = 1 << 5  # Should show: left_shift: int
right_shift = 32 >> 2  # Should show: right_shift: int
bitwise_not = ~10  # Should show: bitwise_not: int

# Boolean bitwise operations (promote to int)
bool_and = True & False  # Should show: bool_and: int
bool_or = True | True  # Should show: bool_or: int

# =============================================================================
# NESTED EXPRESSIONS (NEW - should show hints)
# =============================================================================

# Nested arithmetic
nested1 = (5 + 3) * 2  # Should show: nested1: int
nested2 = 10 + (2 * 3)  # Should show: nested2: int
complex_expr = (5 + 3.0) * 2  # Should show: complex_expr: float (due to type promotion)

# Complex type promotion
promotion1 = 5 + 3.0 * 2  # Should show: promotion1: float (3.0 * 2 = 6.0, then 5 + 6.0)
promotion2 = (10 - 2) + 1.5  # Should show: promotion2: float

# =============================================================================
# FUNCTIONS (may show parameter/return hints if propagation works)
# =============================================================================


def add(a, b):
    """Simple addition function."""
    result = a + b  # Local variable (may show: result: int)
    return result


def greet(person):
    """Simple greeting function."""
    message = "Hello, " + person  # Local variable (may show: message: str)
    return message


def calculate():
    """Function with local variables."""
    x = 42  # Local variable (may show: x: int)
    y = x + 10  # Local variable (may show: y: int)
    return y


def arithmetic_demo():
    """Function demonstrating arithmetic operations."""
    a = 5 + 3  # Should show: a: int
    b = 10.0 / 2  # Should show: b: float
    c = a * 2  # noqa: F841 - Should show: c: int
    d = b + a  # Should show: d: float (type promotion)
    return d


def string_demo():
    """Function demonstrating string operations."""
    first = "Hello"  # Should show: first: str
    second = " World"  # Should show: second: str
    combined = first + second  # Should show: combined: str
    repeated = "-" * 20  # noqa: F841 - Should show: repeated: str
    return combined


def bitwise_demo():
    """Function demonstrating bitwise operations."""
    flags = 0b1010 | 0b0101  # Should show: flags: int
    masked = flags & 0xFF  # noqa: F841 - Should show: masked: int
    shifted = 1 << 8  # noqa: F841 - Should show: shifted: int
    return flags


def collection_demo():
    """Function demonstrating collection operations."""
    list1 = [1, 2]  # Should show: list1: list
    list2 = [3, 4]  # Should show: list2: list
    combined = list1 + list2  # Should show: combined: list
    repeated = [0] * 10  # noqa: F841 - Should show: repeated: list
    return combined


# =============================================================================
# FUNCTION CALLS (may show hints if return types are inferred)
# =============================================================================

total = add(5, 10)  # May show: total: int (if add's return is inferred)
msg = greet("Bob")  # May show: msg: str (if greet's return is inferred)
answer = calculate()  # May show: answer: int (if calculate's return is inferred)

# New function calls
calc_result = arithmetic_demo()  # May show: calc_result: float
str_result = string_demo()  # May show: str_result: str
bit_result = bitwise_demo()  # May show: bit_result: int
list_result = collection_demo()  # May show: list_result: list

# =============================================================================
# EDGE CASES & DEMONSTRATIONS
# =============================================================================

# These should NOT show hints (incompatible types)
# incompatible = 5 + "hello"  # Would show: incompatible: (no hint - Unknown type)

# Variables referencing other variables (contextual inference)
base = 100  # Should show: base: int
derived = base + 50  # Should show: derived: int
doubled = derived * 2  # Should show: doubled: int

# Complex nested expressions
complex1 = (10 + 5) * (3 - 1)  # Should show: complex1: int
complex2 = ((2 + 3) * 4) / 2  # Should show: complex2: float (division always float)

# Mixed operations with all types
all_ints = 1 + 2 - 3 * 4 // 5 % 6  # Should show: all_ints: int
with_float = 1 + 2.0 * 3  # Should show: with_float: float
