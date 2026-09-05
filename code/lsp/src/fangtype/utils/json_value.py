"""Recursive type alias modeling decoded JSON / raw LSP payloads for isinstance narrowing."""

type JSONValue = bool | int | float | str | list[JSONValue] | dict[str, JSONValue] | None
