"""URI handling utilities for LSP server."""

import logging
import platform
from urllib.parse import unquote

from fangtype.utils.json_value import JSONValue

logger = logging.getLogger(__name__)


class UriHelper:
    """Helper class for URI operations in LSP context."""

    @staticmethod
    def uri_to_path(uri: str) -> str | None:
        """Convert a file:// URI to a filesystem path, or None if not a file URI."""
        if uri.startswith("file://"):
            path = unquote(uri[7:])
            if platform.system() == "Windows" and path.startswith("/"):
                path = path[1:]
            return path
        return None

    @staticmethod
    def extract_uri(params: JSONValue) -> str:
        """Extract a URI from LSP params, unwrapping nesting; raises ValueError if invalid."""
        if isinstance(params, str):
            # Direct string (unwrapped)
            return params
        if isinstance(params, list) and len(params) > 0:
            # Check if double-wrapped: [[uri]] or single-wrapped: [uri]
            first = params[0]
            if isinstance(first, list) and len(first) > 0:
                # Double-wrapped: [[uri]]
                logger.warning(f"Received double-wrapped parameters: {params!r}")
                return str(first[0])
            # Single-wrapped: [uri]
            return str(first)
        raise ValueError(f"Invalid params structure: {params!r}")

    @staticmethod
    def extract_uri_with_optional_params(
        params: JSONValue, num_optional: int = 1
    ) -> tuple[str, list[JSONValue]]:
        """Extract (uri, opt_params) from LSP params, padded to num_optional; ValueError if bad."""
        uri: str
        optional_params: list[JSONValue] = [None] * num_optional

        if isinstance(params, str):
            # Direct string (unwrapped) - just URI
            uri = params
        elif isinstance(params, list) and len(params) > 0:
            # Check for different wrapping levels
            first = params[0]
            if isinstance(first, list) and len(first) > 0:
                # Double-wrapped: [[uri, ...]]
                uri = str(first[0])
                # Extract optional parameters
                for i in range(num_optional):
                    if len(first) > i + 1:
                        optional_params[i] = first[i + 1]
                logger.warning(f"Received double-wrapped parameters: {params!r}")
            else:
                # Single-wrapped: [uri, ...]
                uri = str(params[0])
                # Extract optional parameters
                for i in range(num_optional):
                    if len(params) > i + 1:
                        optional_params[i] = params[i + 1]
        else:
            raise ValueError(f"Invalid params structure: {params!r}")

        return uri, optional_params
