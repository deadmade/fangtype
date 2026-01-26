"""Auto Type - Python automatic type inference tool.

An interactive Language Server Protocol (LSP) implementation that provides
type inference for Python code, displaying inferred types as ghost text
in compatible editors.
"""

import importlib.metadata

from auto_type.container import get_container, reset_container, set_container

try:
    __version__ = importlib.metadata.version("auto-type")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0-dev"

__all__: list[str] = [
    "__version__",
    "get_container",
    "reset_container",
    "set_container",
]
