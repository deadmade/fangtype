"""Import and module patterns for testing Auto Type extension.

Tests various import styles and module structures:
- Standard library imports
- Multiple import styles
- Renamed imports (as)
- From imports
- Star imports
- Conditional imports (TYPE_CHECKING)
- Using types from imported modules

Expected: Correct type hints for imported types and functions.
"""

from __future__ import annotations

# Renamed imports
import json
import json as json_lib
import re
from collections import Counter, defaultdict, deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, auto
from functools import lru_cache, partial, reduce
from itertools import chain, combinations, groupby, product
from operator import add, itemgetter, mul
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

# =============================================================================
# USING STANDARD LIBRARY TYPES
# =============================================================================


def use_pathlib():
    """Use Path from pathlib."""
    home = Path.home()  # Expected hint: home: Path
    current = Path.cwd()  # Expected hint: current: Path
    file_path = current / "test.txt"  # Expected hint: file_path: Path

    exists = file_path.exists()  # Expected hint: exists: bool
    is_file = file_path.is_file()  # Expected hint: is_file: bool

    return home, current, file_path


def use_datetime():
    """Use datetime module."""
    now = datetime.now()  # Expected hint: now: datetime
    today = datetime.today()  # Expected hint: today: datetime

    delta = timedelta(days=7)  # Expected hint: delta: timedelta
    future = now + delta  # Expected hint: future: datetime

    formatted = now.isoformat()  # Expected hint: formatted: str
    timestamp = now.timestamp()  # Expected hint: timestamp: float

    return now, future, formatted


def use_json():
    """Use json module."""
    data = {"key": "value", "number": 42}  # Expected hint: data: dict

    # Encode to JSON string
    json_str = json.dumps(data)  # Expected hint: json_str: str

    # Decode from JSON string
    decoded = json.loads(
        json_str
    )  # Expected hint: decoded: dict | list | str | int | float | bool | None

    # With indent
    pretty = json.dumps(data, indent=2)  # Expected hint: pretty: str

    return json_str, decoded, pretty


def use_renamed_json():
    """Use renamed json import."""
    data = [1, 2, 3]  # Expected hint: data: list
    encoded = json_lib.dumps(data)  # Expected hint: encoded: str
    decoded = json_lib.loads(
        encoded
    )  # Expected hint: decoded: dict | list | str | int | float | bool | None
    return encoded, decoded


def use_regex():
    """Use regex module."""
    pattern = re.compile(r"\d+")  # Expected hint: pattern: Pattern[str]
    text = "The answer is 42"  # Expected hint: text: str

    match = pattern.search(text)  # Expected hint: match: Match[str] | None
    if match:
        found = match.group()  # Expected hint: found: str
        number = int(found)  # Expected hint: number: int
        return number

    return None


def use_urlparse():
    """Use urllib.parse."""
    url = (
        "https://example.com:8080/path?query=value#fragment"  # Expected hint: url: str
    )
    parsed = urlparse(url)  # Expected hint: parsed: ParseResult

    scheme = parsed.scheme  # Expected hint: scheme: str
    netloc = parsed.netloc  # Expected hint: netloc: str
    path = parsed.path  # Expected hint: path: str
    query = parsed.query  # Expected hint: query: str

    return scheme, netloc, path, query


# =============================================================================
# USING COLLECTIONS MODULE
# =============================================================================


def use_counter():
    """Use Counter from collections."""
    data = [1, 2, 2, 3, 3, 3, 4, 4, 4, 4]  # Expected hint: data: list
    counter = Counter(data)  # Expected hint: counter: Counter[int]

    most_common = counter.most_common(
        2
    )  # Expected hint: most_common: list[tuple[int, int]]
    total = counter.total()  # Expected hint: total: int

    return counter, most_common


def use_defaultdict():
    """Use defaultdict from collections."""
    dd = defaultdict(list)  # Expected hint: dd: defaultdict[Any, list]

    dd["key1"].append(1)
    dd["key2"].append(2)

    keys = list(dd.keys())  # Expected hint: keys: list
    values = list(dd.values())  # Expected hint: values: list

    return dd, keys, values


def use_deque():
    """Use deque from collections."""
    dq = deque([1, 2, 3])  # Expected hint: dq: deque[int]

    dq.append(4)
    dq.appendleft(0)

    popped = dq.pop()  # Expected hint: popped: int
    popped_left = dq.popleft()  # Expected hint: popped_left: int

    return dq, popped, popped_left


# =============================================================================
# USING FUNCTOOLS
# =============================================================================


def use_lru_cache():
    """Use lru_cache decorator."""

    @lru_cache(maxsize=128)
    def fibonacci(n):
        if n <= 1:
            return n
        return fibonacci(n - 1) + fibonacci(n - 2)

    result = fibonacci(10)  # Expected hint: result: int
    cache_info = fibonacci.cache_info()  # Expected hint: cache_info: CacheInfo

    return result, cache_info


def use_partial():
    """Use functools.partial."""

    def power(base, exponent):
        return base**exponent

    square = partial(power, exponent=2)  # Expected hint: square: partial[int]
    cube = partial(power, exponent=3)  # Expected hint: cube: partial[int]

    result1 = square(5)  # Expected hint: result1: int
    result2 = cube(3)  # Expected hint: result2: int

    return result1, result2


def use_reduce():
    """Use functools.reduce."""
    numbers = [1, 2, 3, 4, 5]  # Expected hint: numbers: list

    sum_result = reduce(add, numbers)  # Expected hint: sum_result: int
    product_result = reduce(mul, numbers)  # Expected hint: product_result: int

    return sum_result, product_result


# =============================================================================
# USING ITERTOOLS
# =============================================================================


def use_chain():
    """Use itertools.chain."""
    list1 = [1, 2, 3]  # Expected hint: list1: list
    list2 = [4, 5, 6]  # Expected hint: list2: list
    list3 = [7, 8, 9]  # Expected hint: list3: list

    chained = list(chain(list1, list2, list3))  # Expected hint: chained: list

    return chained


def use_combinations():
    """Use itertools.combinations."""
    data = [1, 2, 3, 4]  # Expected hint: data: list

    pairs = list(combinations(data, 2))  # Expected hint: pairs: list
    triples = list(combinations(data, 3))  # Expected hint: triples: list

    return pairs, triples


def use_product():
    """Use itertools.product."""
    colors = ["red", "blue"]  # Expected hint: colors: list
    sizes = ["S", "M", "L"]  # Expected hint: sizes: list

    products = list(product(colors, sizes))  # Expected hint: products: list

    return products


def use_groupby():
    """Use itertools.groupby."""
    data = [1, 1, 2, 2, 2, 3, 3, 1, 1]  # Expected hint: data: list

    groups = [(k, list(g)) for k, g in groupby(data)]  # Expected hint: groups: list

    return groups


# =============================================================================
# USING OPERATOR MODULE
# =============================================================================


def use_operators():
    """Use operator module functions."""
    numbers = [5, 2, 8, 1, 9]  # Expected hint: numbers: list

    sum_result = reduce(add, numbers)  # Expected hint: sum_result: int
    product = reduce(mul, numbers)  # Expected hint: product: int

    # Use with sorted
    data = [("Alice", 30), ("Bob", 25), ("Charlie", 35)]  # Expected hint: data: list
    sorted_by_name = sorted(
        data, key=itemgetter(0)
    )  # Expected hint: sorted_by_name: list
    sorted_by_age = sorted(
        data, key=itemgetter(1)
    )  # Expected hint: sorted_by_age: list

    return sum_result, product, sorted_by_name, sorted_by_age


# =============================================================================
# USING DATACLASSES
# =============================================================================


@dataclass
class Person:
    """Person dataclass."""

    name: str
    age: int
    email: str = ""
    tags: list[str] = field(default_factory=list)


def use_dataclass():
    """Use dataclass."""
    person = Person(name="Alice", age=30)  # Expected hint: person: Person

    name = person.name  # Expected hint: name: str
    age = person.age  # Expected hint: age: int

    # Modify
    person.email = "alice@example.com"
    person.tags.append("developer")

    return person


# =============================================================================
# USING ENUMS
# =============================================================================


class Status(Enum):
    """Status enumeration."""

    PENDING = auto()
    ACTIVE = auto()
    COMPLETED = auto()
    FAILED = auto()


def use_enum():
    """Use enum."""
    status = Status.PENDING  # Expected hint: status: Status

    name = status.name  # Expected hint: name: str
    value = status.value  # Expected hint: value: int

    # Compare
    is_pending = status == Status.PENDING  # Expected hint: is_pending: bool

    # Iterate
    all_statuses = list(Status)  # Expected hint: all_statuses: list[Status]

    return status, name, value, all_statuses


# =============================================================================
# TYPE_CHECKING IMPORTS
# =============================================================================

if TYPE_CHECKING:
    from typing import Protocol

    class Drawable(Protocol):
        def draw(self) -> str: ...


def use_type_checking_import(obj):
    """Use TYPE_CHECKING import."""
    # This would normally use the Drawable protocol
    if hasattr(obj, "draw"):
        result = obj.draw()  # Expected hint: result: Any
        return result
    return "No draw method"


# =============================================================================
# USING COLLECTIONS.ABC
# =============================================================================


def use_collections_abc(items):
    """Use collections.abc types."""
    # Check instance
    is_sequence = isinstance(items, Sequence)  # Expected hint: is_sequence: bool
    is_iterable = isinstance(items, Iterable)  # Expected hint: is_iterable: bool
    is_mapping = isinstance(items, Mapping)  # Expected hint: is_mapping: bool

    return is_sequence, is_iterable, is_mapping


# =============================================================================
# COMPLEX IMPORT USAGE
# =============================================================================


def process_file_path(filepath):
    """Process file path using multiple imports."""
    path = Path(filepath)  # Expected hint: path: Path

    # Check existence
    if not path.exists():
        return None

    # Read file
    content = path.read_text()  # Expected hint: content: str

    # Parse as JSON
    try:
        data = json.loads(
            content
        )  # Expected hint: data: dict | list | str | int | float | bool | None
    except json.JSONDecodeError as e:
        error = str(e)  # Expected hint: error: str
        return {"error": error}

    return data


def analyze_text(text):
    """Analyze text using multiple imports."""
    # Split into words
    words = text.split()  # Expected hint: words: list

    # Count words
    word_count = len(words)  # Expected hint: word_count: int

    # Count frequencies
    counter = Counter(words)  # Expected hint: counter: Counter[str]
    most_common = counter.most_common(5)  # Expected hint: most_common: list

    # Find URLs
    url_pattern = re.compile(
        r"https?://\S+"
    )  # Expected hint: url_pattern: Pattern[str]
    urls = url_pattern.findall(text)  # Expected hint: urls: list[str]

    result = {  # Expected hint: result: dict
        "word_count": word_count,
        "most_common": most_common,
        "url_count": len(urls),
    }

    return result


def combine_and_process(data_sources):
    """Combine data from multiple sources."""
    # Combine all data
    combined = list(chain.from_iterable(data_sources))  # Expected hint: combined: list

    # Remove duplicates
    unique = list(set(combined))  # Expected hint: unique: list

    # Sort
    sorted_data = sorted(unique)  # Expected hint: sorted_data: list

    # Group by type
    by_type = defaultdict(list)  # Expected hint: by_type: defaultdict
    for item in sorted_data:
        item_type = type(item).__name__  # Expected hint: item_type: str
        by_type[item_type].append(item)

    return dict(by_type)


# =============================================================================
# EXAMPLE USAGE
# =============================================================================


def demonstrate_imports():
    """Demonstrate import usage."""
    # Pathlib
    paths = use_pathlib()  # Expected hint: paths: tuple

    # Datetime
    dates = use_datetime()  # Expected hint: dates: tuple

    # JSON
    json_results = use_json()  # Expected hint: json_results: tuple

    # Collections
    counter_result = use_counter()  # Expected hint: counter_result: tuple

    # Functools
    reduce_result = use_reduce()  # Expected hint: reduce_result: tuple

    # Itertools
    chain_result = use_chain()  # Expected hint: chain_result: list

    # Dataclass
    person = use_dataclass()  # Expected hint: person: Person

    # Enum
    enum_result = use_enum()  # Expected hint: enum_result: tuple

    summary = {  # Expected hint: summary: dict
        "paths": len(paths),
        "dates": len(dates),
        "json": len(json_results),
        "person": person.name,
        "enum": enum_result[1],
    }

    return summary


if __name__ == "__main__":
    result = demonstrate_imports()  # Expected hint: result: dict
    print(f"Import examples: {result}")
