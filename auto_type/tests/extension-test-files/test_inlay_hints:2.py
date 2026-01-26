x = 42
name = "Alice"
items = [1, 2, 3]
data = {"key": "value", "count": 10}


def greet(name):
    message = f"Hello, {name}"
    return message


def process_items(items):
    result = []
    for item in items:
        processed = item * 2
        result.append(processed)
    return result


result = greet("World")
numbers = process_items([1, 2, 3, 4, 5])
