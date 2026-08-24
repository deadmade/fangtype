"""Tests for LSP request helper utilities."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from lsprotocol import types

from fangtype.utils.lsp_request_helper import (
    build_full_document_workspace_edit,
    extract_uri_and_context,
    get_document_context,
)


def _make_ls_with_source(source: str, version: int | None = None) -> MagicMock:
    """Create a mock language server with workspace document source."""
    ls = MagicMock()
    ls.workspace.get_text_document.return_value = SimpleNamespace(source=source, version=version)
    return ls


def test_get_document_context_resolves_source_and_file_path() -> None:
    """It returns source text and filesystem path for file URIs."""
    uri = "file:///tmp/example.py"
    ls = _make_ls_with_source("x = 1\n", version=7)

    context = get_document_context(ls, uri)

    assert context.uri == uri
    assert context.source == "x = 1\n"
    assert context.file_path == "/tmp/example.py"
    assert context.version == 7


def test_extract_uri_and_context_with_optional_params() -> None:
    """It extracts optional args and resolves the linked document context."""
    uri = "file:///tmp/params.py"
    ls = _make_ls_with_source("value = 2\n")

    context, optional = extract_uri_and_context(ls, [uri, 10, 20], num_optional=2)

    assert context.uri == uri
    assert context.source == "value = 2\n"
    assert optional == [10, 20]


def test_build_full_document_workspace_edit_replaces_entire_document() -> None:
    """It creates one versioned full-file edit with expected range and replacement."""
    uri = "file:///tmp/edit.py"
    source = "a = 1\nb = 2\n"
    new_source = "a: int = 1\nb: int = 2\n"

    edit = build_full_document_workspace_edit(uri, source, new_source, version=3)
    # Emitted in the versioned documentChanges form, not the legacy changes map.
    assert edit.changes is None
    assert edit.document_changes is not None
    text_document_edit = edit.document_changes[0]
    assert isinstance(text_document_edit, types.TextDocumentEdit)
    assert text_document_edit.text_document.uri == uri
    assert text_document_edit.text_document.version == 3
    text_edit = text_document_edit.edits[0]
    assert isinstance(text_edit, types.TextEdit)

    assert text_edit.range.start.line == 0
    assert text_edit.range.start.character == 0
    assert text_edit.range.end.line == len(source.splitlines())
    assert text_edit.range.end.character == 0
    assert text_edit.new_text == new_source


def test_build_full_document_workspace_edit_defaults_version_none() -> None:
    """Without a version the identifier carries ``None`` (client refuses the replace)."""
    edit = build_full_document_workspace_edit("file:///x.py", "a\n", "a\n")
    assert edit.document_changes is not None
    text_document_edit = edit.document_changes[0]
    assert isinstance(text_document_edit, types.TextDocumentEdit)
    assert text_document_edit.text_document.version is None
