"""Utility helpers for LSP operations, configuration, and URI/type string manipulation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fangtype.utils.document_cache import DocumentCache
from fangtype.utils.lsp_request_helper import (
    build_full_document_workspace_edit,
    extract_uri_and_context,
    get_document_context,
)
from fangtype.utils.settings import Settings

if TYPE_CHECKING:
    from fangtype.utils.code_action_helper import CodeActionHelper
    from fangtype.utils.inlay_hint_helper import InlayHintHelper


def __getattr__(name: str) -> type[CodeActionHelper] | type[InlayHintHelper]:
    """Lazily re-export the helpers to avoid the fangtype.insertion import cycle."""
    if name == "CodeActionHelper":
        from fangtype.utils.code_action_helper import CodeActionHelper

        return CodeActionHelper
    if name == "InlayHintHelper":
        from fangtype.utils.inlay_hint_helper import InlayHintHelper

        return InlayHintHelper
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "CodeActionHelper",
    "DocumentCache",
    "InlayHintHelper",
    "Settings",
    "build_full_document_workspace_edit",
    "extract_uri_and_context",
    "get_document_context",
]
