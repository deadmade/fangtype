"""Utility modules for auto_type.

This package provides helper classes and functions for various LSP operations,
configuration management, and URI/type string manipulation.
"""

from auto_type.utils.code_action_helper import CodeActionHelper
from auto_type.utils.inlay_hint_helper import InlayHintHelper
from auto_type.utils.lsp_request_helper import (
    DocumentContext,
    build_full_document_workspace_edit,
    extract_uri_and_context,
    get_document_context,
)
from auto_type.utils.settings import Settings
from auto_type.inference.type_utils import normalize_type_name, simplify_union_type, split_type_args
from auto_type.utils.uri_helper import UriHelper

__all__ = [
    "CodeActionHelper",
    "DocumentContext",
    "InlayHintHelper",
    "Settings",
    "UriHelper",
    "build_full_document_workspace_edit",
    "extract_uri_and_context",
    "get_document_context",
    "normalize_type_name",
    "simplify_union_type",
    "split_type_args",
]
