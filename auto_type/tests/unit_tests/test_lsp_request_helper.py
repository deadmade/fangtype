"""Tests for LSP request helper utilities."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from auto_type.utils.lsp_request_helper import (
    build_full_document_workspace_edit,
    extract_uri_and_context,
    get_document_context,
)


def _make_ls_with_source(source: str) -> MagicMock:
    """Create a mock language server with workspace document source."""
    ls = MagicMock()
    ls.workspace.get_text_document.return_value = SimpleNamespace(source=source)
    return ls


def test_get_document_context_resolves_source_and_file_path() -> None:
    """It returns source text and filesystem path for file URIs."""
    uri = "file:///tmp/example.py"
    ls = _make_ls_with_source("x = 1\n")

    context = get_document_context(ls, uri)

    assert context.uri == uri
    assert context.source == "x = 1\n"
    assert context.file_path == "/tmp/example.py"


def test_extract_uri_and_context_with_optional_params() -> None:
    """It extracts optional args and resolves the linked document context."""
    uri = "file:///tmp/params.py"
    ls = _make_ls_with_source("value = 2\n")

    context, optional = extract_uri_and_context(ls, [uri, 10, 20], num_optional=2)

    assert context.uri == uri
    assert context.source == "value = 2\n"
    assert optional == [10, 20]


def test_build_full_document_workspace_edit_replaces_entire_document() -> None:
    """It creates one full-file edit with expected range and replacement."""
    uri = "file:///tmp/edit.py"
    source = "a = 1\nb = 2\n"
    new_source = "a: int = 1\nb: int = 2\n"

    edit = build_full_document_workspace_edit(uri, source, new_source)
    text_edit = edit.changes[uri][0]

    assert text_edit.range.start.line == 0
    assert text_edit.range.start.character == 0
    assert text_edit.range.end.line == len(source.splitlines())
    assert text_edit.range.end.character == 0
    assert text_edit.new_text == new_source
