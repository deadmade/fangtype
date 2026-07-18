"""Shared helpers for LSP request document/edit handling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from lsprotocol import types

from fangtype.utils.uri_helper import UriHelper

if TYPE_CHECKING:
    from pygls.lsp.server import LanguageServer

    from fangtype.utils.json_value import JSONValue


@dataclass(frozen=True)
class DocumentContext:
    """Resolved data for a text document request."""

    uri: str
    source: str
    file_path: str
    version: int | None = None


def get_document_context(ls: LanguageServer, uri: str) -> DocumentContext:
    """Resolve context (text, path, version) for a URI; version guards stale edits."""
    doc = ls.workspace.get_text_document(uri)
    return DocumentContext(
        uri=uri,
        source=doc.source,
        file_path=UriHelper.uri_to_path(uri) or "",
        version=doc.version,
    )


def extract_uri_and_context(
    ls: LanguageServer,
    params: JSONValue,
    num_optional: int = 0,
) -> tuple[DocumentContext, list[JSONValue]]:
    """Extract URI (plus num_optional trailing args) from params; return context and params."""
    optional_params: list[JSONValue] = []
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
    version: int | None = None,
) -> types.WorkspaceEdit:
    """Full-document replacement as versioned documentChanges so stale applies are rejected."""
    text_edit = types.TextEdit(
        range=types.Range(
            start=types.Position(line=0, character=0),
            end=types.Position(line=len(source.splitlines()), character=0),
        ),
        new_text=new_source,
    )
    return types.WorkspaceEdit(
        document_changes=[
            types.TextDocumentEdit(
                text_document=types.OptionalVersionedTextDocumentIdentifier(
                    uri=uri, version=version
                ),
                edits=[text_edit],
            )
        ]
    )
