"""Shared helpers for LSP request document/edit handling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from lsprotocol import types

from auto_type.utils.uri_helper import UriHelper

if TYPE_CHECKING:
    from pygls.lsp.server import LanguageServer
    from pygls.workspace import TextDocument


@dataclass(frozen=True)
class DocumentContext:
    """Resolved data for a text document request."""

    uri: str
    source: str
    file_path: str
    document: TextDocument


def get_document_context(ls: LanguageServer, uri: str) -> DocumentContext:
    """Resolve document context for a URI.

    Args:
        ls: Language server instance
        uri: Document URI

    Returns:
        Document context containing text and derived file path
    """
    doc = ls.workspace.get_text_document(uri)
    return DocumentContext(
        uri=uri,
        source=doc.source,
        file_path=UriHelper.uri_to_path(uri) or "",
        document=doc,
    )


def extract_uri_and_context(
    ls: LanguageServer,
    params: Any,
    num_optional: int = 0,
) -> tuple[DocumentContext, list[Any]]:
    """Extract URI and resolve document context from request params.

    Args:
        ls: Language server instance
        params: Raw request params (wrapped or unwrapped)
        num_optional: Number of optional args to extract after URI

    Returns:
        Tuple of (document context, optional params)
    """
    optional_params: list[Any] = []
    if num_optional > 0:
        uri, optional_params = UriHelper.extract_uri_with_optional_params(
            params, num_optional=num_optional
        )
    else:
        uri = UriHelper.extract_uri(params)

    return get_document_context(ls, uri), optional_params


def build_full_document_workspace_edit(
    uri: str,
    source: str,
    new_source: str,
) -> types.WorkspaceEdit:
    """Build a full-document replacement workspace edit.

    Args:
        uri: Document URI
        source: Existing source text
        new_source: Replacement source text

    Returns:
        Workspace edit replacing the full document
    """
    text_edit = types.TextEdit(
        range=types.Range(
            start=types.Position(line=0, character=0),
            end=types.Position(line=len(source.splitlines()), character=0),
        ),
        new_text=new_source,
    )
    return types.WorkspaceEdit(changes={uri: [text_edit]})
