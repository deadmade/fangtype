x: str = 42
y: int = "hello"
z: list[str] = [1, 2, 3]


def calculate():
    """Function with local variables."""
    x = 42  # Local variable (may show: x: int)
    y = x + 10  # Local variable (may show: y: int)
    return y


def add(a, b):
    """Simple addition function."""
    result = a + b  # Local variable (may show: result: int)
    return result


g: int = add(1, 2)

print(g)
