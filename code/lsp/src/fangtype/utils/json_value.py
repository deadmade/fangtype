"""Recursive type alias modeling decoded JSON / raw LSP payloads for isinstance narrowing."""

type JSONValue = None | bool | int | float | str | list[JSONValue] | dict[str, JSONValue]
