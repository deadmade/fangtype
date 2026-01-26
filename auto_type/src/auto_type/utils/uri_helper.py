"""URI handling utilities for LSP server."""

import logging
import platform
from typing import Any
from urllib.parse import unquote

logger = logging.getLogger(__name__)


class UriHelper:
    """Helper class for URI operations in LSP context."""

    @staticmethod
    def uri_to_path(uri: str) -> str | None:
        """Convert file:// URI to filesystem path.

        Args:
            uri: File URI (e.g., "file:///path/to/file.py")

        Returns:
            Filesystem path or None if not a file URI
        """
        if uri.startswith("file://"):
            path = unquote(uri[7:])
            if platform.system() == "Windows" and path.startswith("/"):
                path = path[1:]
            return path
        return None

    @staticmethod
    def extract_uri(params: Any) -> str:
        """Extract URI from LSP request parameters with defensive handling.

        Handles various parameter wrapping levels:
        - Direct string: "file:///path"
        - Single-wrapped: ["file:///path"]
        - Double-wrapped: [["file:///path"]]

        Args:
            params: LSP request parameters (can be str, list, or nested list)

        Returns:
            Extracted URI string

        Raises:
            ValueError: If params structure is invalid
        """
        if isinstance(params, str):
            # Direct string (unwrapped)
            return params
        elif isinstance(params, list) and len(params) > 0:
            # Check if double-wrapped: [[uri]] or single-wrapped: [uri]
            if isinstance(params[0], list) and len(params[0]) > 0:
                # Double-wrapped: [[uri]]
                logger.warning(f"Received double-wrapped parameters: {params!r}")
                return str(params[0][0])
            else:
                # Single-wrapped: [uri]
                return str(params[0])
        else:
            raise ValueError(f"Invalid params structure: {params!r}")

    @staticmethod
    def extract_uri_with_optional_params(
        params: Any, num_optional: int = 1
    ) -> tuple[str, list[Any]]:
        """Extract URI and optional parameters from LSP request with defensive handling.

        Handles various parameter wrapping levels:
        - Direct string: "file:///path" -> ("file:///path", [])
        - Single-wrapped: ["file:///path", ...] -> ("file:///path", [...])
        - Double-wrapped: [["file:///path", ...]] -> ("file:///path", [...])

        Args:
            params: LSP request parameters
            num_optional: Number of optional parameters to extract (default: 1)

        Returns:
            Tuple of (uri, list of optional parameters)
            Optional parameters list length matches num_optional (None for missing params)

        Raises:
            ValueError: If params structure is invalid
        """
        uri: str
        optional_params: list[Any] = [None] * num_optional

        if isinstance(params, str):
            # Direct string (unwrapped) - just URI
            uri = params
        elif isinstance(params, list) and len(params) > 0:
            # Check for different wrapping levels
            if isinstance(params[0], list) and len(params[0]) > 0:
                # Double-wrapped: [[uri, ...]]
                inner = params[0]
                uri = str(inner[0])
                # Extract optional parameters
                for i in range(num_optional):
                    if len(inner) > i + 1:
                        optional_params[i] = inner[i + 1]
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
