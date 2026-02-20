# Container type assignments with annotations
# Expected output after insertion
from typing import Any

list_of_ints: list[int] = [1, 2, 3, 4, 5]
list_of_strings: list[str] = ["a", "b", "c"]
empty_list: list[Any] = []
nested_list: list[list[int]] = [[1, 2], [3, 4]]

dict_str_int: dict[str, int] = {"alice": 30, "bob": 25}
dict_str_str: dict[str, str] = {"key": "value", "foo": "bar"}
empty_dict: dict[Any, Any] = {}

set_of_ints: set[int] = {1, 2, 3}
set_of_strings: set[str] = {"a", "b", "c"}

tuple_two: tuple[int, int] = (1, 2)
tuple_mixed: tuple[int, str, bool] = (1, "hello", True)
