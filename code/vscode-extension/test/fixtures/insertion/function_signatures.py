# Function signatures for insertion testing
# Test file for function parameter and return type annotations


def greet(name, age):
    """Greet a person with their name and age."""
    return f"Hello {name}, you are {age} years old"


def add(a, b):
    """Add two numbers."""
    return a + b


def is_even(n):
    """Check if a number is even."""
    return n % 2 == 0


def get_items():
    """Return a list of items."""
    return [1, 2, 3]


def process_data(data, flag):
    """Process data with a flag."""
    if flag:
        return data.upper()
    return data


def no_params():
    """Function with no parameters."""
    return 42


def no_return(x):
    """Function with no return value."""
    print(x)
