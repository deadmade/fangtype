"""Functional programming patterns for testing Auto Type extension.

Demonstrates:
- Decorators and decorator factories
- Closures and captured variables
- Higher-order functions
- Generator functions and expressions
- Complex comprehensions
- Functools patterns (partial, reduce, compose)
- Lambda expressions and functional composition

Expected: Accurate type hints for closures, decorators, and functional patterns.
"""

from __future__ import annotations

import functools
import itertools
from operator import add, mul
from typing import TypeVar

T = TypeVar("T")
R = TypeVar("R")


# =============================================================================
# DECORATORS
# =============================================================================


def simple_decorator(func):
    """Simple function decorator."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        result = func(*args, **kwargs)  # Expected hint: result: Any
        return result

    return wrapper


def logging_decorator(func):
    """Decorator that logs function calls."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        func_name = func.__name__  # Expected hint: func_name: str
        print(f"Calling {func_name}")
        result = func(*args, **kwargs)  # Expected hint: result: Any
        print(f"Finished {func_name}")
        return result

    return wrapper


def timing_decorator(func):
    """Decorator that times function execution."""
    import time

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()  # Expected hint: start: float
        result = func(*args, **kwargs)  # Expected hint: result: Any
        end = time.time()  # Expected hint: end: float
        duration = end - start  # Expected hint: duration: float
        print(f"{func.__name__} took {duration:.4f}s")
        return result

    return wrapper


def retry_decorator(max_attempts):
    """Decorator factory for retry logic."""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            attempts = 0  # Expected hint: attempts: int
            while attempts < max_attempts:
                try:
                    result = func(*args, **kwargs)  # Expected hint: result: Any
                    return result
                except Exception as e:
                    attempts += 1
                    error_msg = str(e)  # Expected hint: error_msg: str
                    if attempts >= max_attempts:
                        raise
            return None

        return wrapper

    return decorator


def memoize(func):
    """Memoization decorator."""
    cache = {}  # Expected hint: cache: dict

    @functools.wraps(func)
    def wrapper(*args):
        if args in cache:
            return cache[args]
        result = func(*args)  # Expected hint: result: Any
        cache[args] = result
        return result

    return wrapper


def validate_args(*types):
    """Decorator factory for argument validation."""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for arg, expected_type in zip(args, types):
                if not isinstance(arg, expected_type):
                    type_name = expected_type.__name__  # Expected hint: type_name: str
                    raise TypeError(f"Expected {type_name}")
            return func(*args, **kwargs)

        return wrapper

    return decorator


@logging_decorator
@timing_decorator
def decorated_function(x, y):
    """Function with multiple decorators."""
    result = x + y  # Expected hint: result: int | str | float
    return result


# =============================================================================
# CLOSURES
# =============================================================================


def make_multiplier(factor):
    """Create a multiplier function (closure)."""

    def multiply(x):
        result = x * factor  # Expected hint: result: int | float
        return result

    return multiply


def make_adder(base):
    """Create an adder function."""

    def add_to_base(value):
        result = base + value  # Expected hint: result: int | float
        return result

    return add_to_base


def make_counter(start=0):
    """Create a counter closure."""
    count = [start]  # Expected hint: count: list (mutable closure variable)

    def increment():
        count[0] += 1
        return count[0]

    def decrement():
        count[0] -= 1
        return count[0]

    def get_count():
        return count[0]

    return increment, decrement, get_count


def make_accumulator(initial=0):
    """Create an accumulator closure."""
    total = [initial]  # Expected hint: total: list

    def add(value):
        total[0] += value
        return total[0]

    def reset():
        total[0] = initial
        return total[0]

    return add, reset


def create_greeting(greeting):
    """Create personalized greeting function."""

    def greet(name):
        message = f"{greeting}, {name}!"  # Expected hint: message: str
        return message

    return greet


# =============================================================================
# HIGHER-ORDER FUNCTIONS
# =============================================================================


def apply_function(func, value):
    """Apply a function to a value."""
    result = func(value)  # Expected hint: result: Any
    return result


def compose(f, g):
    """Compose two functions: f(g(x))."""

    def composed(x):
        inner_result = g(x)  # Expected hint: inner_result: Any
        final_result = f(inner_result)  # Expected hint: final_result: Any
        return final_result

    return composed


def pipe(*functions):
    """Create a pipeline of functions."""

    def piped(initial):
        result = initial  # Expected hint: result: Any
        for func in functions:
            result = func(result)
        return result

    return piped


def map_reduce(mapper, reducer, items, initial):
    """Map-reduce pattern."""
    mapped = [mapper(item) for item in items]  # Expected hint: mapped: list
    result = functools.reduce(reducer, mapped, initial)  # Expected hint: result: Any
    return result


def filter_map(predicate, mapper, items):
    """Filter then map."""
    filtered = [
        item for item in items if predicate(item)
    ]  # Expected hint: filtered: list
    mapped = [mapper(item) for item in filtered]  # Expected hint: mapped: list
    return mapped


def curry(func):
    """Curry a function."""

    @functools.wraps(func)
    def curried(*args, **kwargs):
        if len(args) + len(kwargs) >= func.__code__.co_argcount:
            return func(*args, **kwargs)
        return functools.partial(curried, *args, **kwargs)

    return curried


# =============================================================================
# GENERATOR FUNCTIONS
# =============================================================================


def fibonacci():
    """Generate Fibonacci sequence."""
    a, b = 0, 1  # Expected hint: a: int, b: int
    while True:
        yield a
        temp = a + b  # Expected hint: temp: int
        a, b = b, temp


def range_generator(start, end, step=1):
    """Custom range generator."""
    current = start  # Expected hint: current: int
    while current < end:
        yield current
        current += step


def fibonacci_up_to(n):
    """Generate Fibonacci numbers up to n."""
    a, b = 0, 1  # Expected hint: a: int, b: int
    while a < n:
        yield a
        a, b = b, a + b


def prime_generator():
    """Generate prime numbers."""
    primes = []  # Expected hint: primes: list
    num = 2  # Expected hint: num: int

    while True:
        is_prime = True  # Expected hint: is_prime: bool
        for prime in primes:
            if num % prime == 0:
                is_prime = False
                break
        if is_prime:
            primes.append(num)
            yield num
        num += 1


def chunk_generator(items, size):
    """Generate chunks of specified size."""
    for i in range(0, len(items), size):
        chunk = items[i : i + size]  # Expected hint: chunk: list
        yield chunk


def pairwise(items):
    """Generate consecutive pairs."""
    iterator = iter(items)  # Expected hint: iterator: Iterator
    try:
        prev = next(iterator)  # Expected hint: prev: Any
        for current in iterator:
            pair = (prev, current)  # Expected hint: pair: tuple
            yield pair
            prev = current
    except StopIteration:
        return


def sliding_window(items, window_size):
    """Generate sliding windows."""
    iterator = iter(items)  # Expected hint: iterator: Iterator
    window = list(
        itertools.islice(iterator, window_size)
    )  # Expected hint: window: list

    if len(window) == window_size:
        yield tuple(window)

    for item in iterator:
        window = window[1:] + [item]
        yield tuple(window)


# =============================================================================
# COMPREHENSIONS
# =============================================================================


def list_comprehension_examples():
    """Demonstrate list comprehensions."""
    # Simple comprehension
    squares = [x**2 for x in range(10)]  # Expected hint: squares: list

    # With condition
    evens = [x for x in range(20) if x % 2 == 0]  # Expected hint: evens: list

    # Nested comprehension
    matrix = [
        [i * j for j in range(5)] for i in range(5)
    ]  # Expected hint: matrix: list

    # Multiple conditions
    filtered = [
        x for x in range(100) if x % 2 == 0 if x % 3 == 0
    ]  # Expected hint: filtered: list

    return squares, evens, matrix, filtered


def dict_comprehension_examples():
    """Demonstrate dict comprehensions."""
    # Simple dict comprehension
    squares_dict = {x: x**2 for x in range(10)}  # Expected hint: squares_dict: dict

    # With condition
    even_squares = {
        x: x**2 for x in range(10) if x % 2 == 0
    }  # Expected hint: even_squares: dict

    # Swap keys and values
    original = {"a": 1, "b": 2, "c": 3}  # Expected hint: original: dict
    swapped = {v: k for k, v in original.items()}  # Expected hint: swapped: dict

    # Transform values
    doubled = {k: v * 2 for k, v in original.items()}  # Expected hint: doubled: dict

    return squares_dict, even_squares, swapped, doubled


def set_comprehension_examples():
    """Demonstrate set comprehensions."""
    # Simple set comprehension
    unique_lengths = {
        len(word) for word in ["hello", "world", "test", "hi"]
    }  # Expected hint: unique_lengths: set

    # With condition
    long_lengths = {
        len(word) for word in ["hello", "world", "test"] if len(word) > 4
    }  # Expected hint: long_lengths: set

    return unique_lengths, long_lengths


def generator_expression_examples():
    """Demonstrate generator expressions."""
    # Generator expression
    gen = (x**2 for x in range(10))  # Expected hint: gen: Generator

    # Sum with generator
    total = sum(x**2 for x in range(100))  # Expected hint: total: int

    # Any/all with generator
    has_even = any(x % 2 == 0 for x in range(10))  # Expected hint: has_even: bool
    all_positive = all(x > 0 for x in range(1, 10))  # Expected hint: all_positive: bool

    return total, has_even, all_positive


# =============================================================================
# FUNCTOOLS PATTERNS
# =============================================================================


def partial_application_examples():
    """Demonstrate functools.partial."""
    # Partial with built-in function
    double = functools.partial(mul, 2)  # Expected hint: double: partial[int]
    result1 = double(5)  # Expected hint: result1: int

    # Partial with custom function
    def power(base, exponent):
        return base**exponent

    square = functools.partial(power, exponent=2)  # Expected hint: square: partial
    result2 = square(5)  # Expected hint: result2: int

    # Partial with keyword arguments
    greet = functools.partial(
        print, "Hello", sep=", ", end="!\n"
    )  # Expected hint: greet: partial

    return result1, result2


def reduce_examples():
    """Demonstrate functools.reduce."""
    # Sum with reduce
    numbers = [1, 2, 3, 4, 5]  # Expected hint: numbers: list
    total = functools.reduce(add, numbers)  # Expected hint: total: int

    # Product with reduce
    product = functools.reduce(mul, numbers)  # Expected hint: product: int

    # Max with reduce
    maximum = functools.reduce(
        lambda a, b: a if a > b else b, numbers
    )  # Expected hint: maximum: int

    # String concatenation
    words = ["hello", "world", "test"]  # Expected hint: words: list
    sentence = functools.reduce(
        lambda a, b: f"{a} {b}", words
    )  # Expected hint: sentence: str

    return total, product, maximum, sentence


def lru_cache_examples():
    """Demonstrate functools.lru_cache."""

    @functools.lru_cache(maxsize=128)
    def expensive_function(n):
        """Simulate expensive computation."""
        result = n**2  # Expected hint: result: int
        return result

    # First call (computes)
    value1 = expensive_function(10)  # Expected hint: value1: int

    # Second call (cached)
    value2 = expensive_function(10)  # Expected hint: value2: int

    # Cache info
    cache_info = expensive_function.cache_info()  # Expected hint: cache_info: CacheInfo

    return value1, value2, cache_info


# =============================================================================
# LAMBDA EXPRESSIONS
# =============================================================================


def lambda_examples():
    """Demonstrate lambda expressions."""
    # Simple lambda
    double = lambda x: x * 2  # Expected hint: double: Callable
    result1 = double(5)  # Expected hint: result1: int

    # Lambda with multiple arguments
    add_lambda = lambda a, b: a + b  # Expected hint: add_lambda: Callable
    result2 = add_lambda(3, 4)  # Expected hint: result2: int

    # Lambda in map
    numbers = [1, 2, 3, 4, 5]  # Expected hint: numbers: list
    doubled = list(map(lambda x: x * 2, numbers))  # Expected hint: doubled: list

    # Lambda in filter
    evens = list(filter(lambda x: x % 2 == 0, numbers))  # Expected hint: evens: list

    # Lambda in sorted
    words = ["banana", "apple", "cherry", "date"]  # Expected hint: words: list
    by_length = sorted(words, key=lambda w: len(w))  # Expected hint: by_length: list

    return result1, result2, doubled, evens, by_length


def complex_lambda_examples():
    """More complex lambda expressions."""
    # Lambda with conditional
    abs_value = lambda x: x if x >= 0 else -x  # Expected hint: abs_value: Callable
    result1 = abs_value(-5)  # Expected hint: result1: int

    # Lambda returning tuple
    swap = lambda a, b: (b, a)  # Expected hint: swap: Callable
    result2 = swap(1, 2)  # Expected hint: result2: tuple

    # Lambda with dict access
    get_name = lambda person: person.get(
        "name", "Unknown"
    )  # Expected hint: get_name: Callable
    result3 = get_name(
        {"name": "Alice", "age": 30}
    )  # Expected hint: result3: str | None

    return result1, result2, result3


# =============================================================================
# ITERTOOLS PATTERNS
# =============================================================================


def itertools_examples():
    """Demonstrate itertools patterns."""
    # Chain iterables
    list1 = [1, 2, 3]  # Expected hint: list1: list
    list2 = [4, 5, 6]  # Expected hint: list2: list
    chained = list(itertools.chain(list1, list2))  # Expected hint: chained: list

    # Zip longest
    a = [1, 2, 3]  # Expected hint: a: list
    b = ["a", "b"]  # Expected hint: b: list
    zipped = list(
        itertools.zip_longest(a, b, fillvalue=None)
    )  # Expected hint: zipped: list

    # Product (Cartesian product)
    colors = ["red", "blue"]  # Expected hint: colors: list
    sizes = ["S", "M", "L"]  # Expected hint: sizes: list
    combinations = list(
        itertools.product(colors, sizes)
    )  # Expected hint: combinations: list

    # Groupby
    data = [1, 1, 2, 2, 2, 3, 3, 1]  # Expected hint: data: list
    groups = [
        (k, list(g)) for k, g in itertools.groupby(data)
    ]  # Expected hint: groups: list

    return chained, zipped, combinations, groups


# =============================================================================
# FUNCTION COMPOSITION
# =============================================================================


def compose_functions():
    """Demonstrate function composition."""
    # Simple composition
    add_one = lambda x: x + 1  # Expected hint: add_one: Callable
    double = lambda x: x * 2  # Expected hint: double: Callable

    composed = compose(double, add_one)  # Expected hint: composed: Callable
    result1 = composed(5)  # Expected hint: result1: Any (12)

    # Pipeline
    increment = lambda x: x + 1  # Expected hint: increment: Callable
    square = lambda x: x**2  # Expected hint: square: Callable
    halve = lambda x: x / 2  # Expected hint: halve: Callable

    pipeline = pipe(increment, square, halve)  # Expected hint: pipeline: Callable
    result2 = pipeline(5)  # Expected hint: result2: Any (18.0)

    return result1, result2


# =============================================================================
# EXAMPLE USAGE
# =============================================================================


def demonstrate_functional_patterns():
    """Demonstrate functional programming patterns."""
    # Decorators
    decorated_result = decorated_function(
        5, 10
    )  # Expected hint: decorated_result: int | str | float

    # Closures
    times_three = make_multiplier(3)  # Expected hint: times_three: Callable
    multiplied = times_three(10)  # Expected hint: multiplied: int | float

    # Generators
    fib_gen = fibonacci()  # Expected hint: fib_gen: Generator
    first_five = [next(fib_gen) for _ in range(5)]  # Expected hint: first_five: list

    # Comprehensions
    squares_result = (
        list_comprehension_examples()
    )  # Expected hint: squares_result: tuple

    # Functools
    reduce_result = reduce_examples()  # Expected hint: reduce_result: tuple

    # Lambda
    lambda_result = lambda_examples()  # Expected hint: lambda_result: tuple

    summary = {  # Expected hint: summary: dict
        "decorated": decorated_result,
        "multiplied": multiplied,
        "first_five_fib": first_five,
        "comprehensions": len(squares_result),
        "reduce": reduce_result[0],
        "lambda": lambda_result[0],
    }

    return summary


if __name__ == "__main__":
    result = demonstrate_functional_patterns()  # Expected hint: result: dict
    print(f"Functional patterns: {result}")
