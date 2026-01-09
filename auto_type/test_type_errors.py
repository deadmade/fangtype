x: str = 42
y: int = "hello"
z: list[str] = [1, 2, 3]


def calculate() -> int:
    """Function with local variables."""
    x: str = 42  # Local variable (may show: x: int)
    y = x + 10  # Local variable (may show: y: int)
    return y
