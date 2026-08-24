"""Fangtype - LSP server providing Python type inference shown as editor ghost text."""

import importlib.metadata

try:
    __version__ = importlib.metadata.version("fangtype")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0-dev"

__all__: list[str] = ["__version__"]
