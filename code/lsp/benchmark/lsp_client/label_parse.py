"""Pure parsing helpers for fangtype LSP responses.

These translate the server's inlay-hint labels and full-document
``WorkspaceEdit`` payloads back into plain type strings / modified source.
"""

from __future__ import annotations

from typing import Any


def _field(obj: Any, *names: str) -> Any:
    """Read a field from either an object (attr) or a mapping (key)."""
    for name in names:
        if isinstance(obj, dict):
            if name in obj:
                return obj[name]
        elif hasattr(obj, name):
            return getattr(obj, name)
    return None


def scrape_inlay_type(label: Any) -> str | None:
    """Extract the inferred type string from an inlay-hint label.

    Labels are annotation-shaped: ``": T"`` for declarations/params, ``"-> T"``
    for returns. ``label`` may be a plain string or a sequence of label parts
    (objects/dicts with a ``value``).

    Returns the bare type string, or ``None`` if empty.
    """
    if isinstance(label, str):
        text = label
    else:
        parts: list[str] = []
        for part in label:
            value = _field(part, "value")
            parts.append(value if isinstance(value, str) else str(part))
        text = "".join(parts)

    text = text.strip()
    for prefix in ("-> ", "->", ": ", ":"):
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
            break

    text = text.lstrip("⚠️ \t")
    return text or None


def modified_source_from_edit(response: Any, uri: str) -> str | None:
    """Reconstruct the modified document from a custom-request response.

    The insert handlers return ``{"success": ..., "edits": <WorkspaceEdit>, ...}``
    where the edit is a single full-document replacement built by
    ``build_full_document_workspace_edit`` — so the one ``TextEdit``'s new text IS
    the whole modified source.

    The server emits the versioned ``documentChanges`` form: a list of
    ``TextDocumentEdit`` (each ``{textDocument: {uri, version}, edits: [TextEdit]}``).
    We match the ``TextDocumentEdit`` for ``uri`` and take its first edit's ``newText``.
    Falls back to the legacy ``changes`` (``{uri: [TextEdit]}``) map for robustness.
    Over the wire either may arrive as a plain ``dict`` (JSON) or, when pygls
    deserializes a custom-request result, as an ``Object`` (a namedtuple subclass).
    """
    edits = _field(response, "edits")
    if edits is None:
        return None

    document_changes = _field(edits, "documentChanges", "document_changes")
    if document_changes is not None:
        for tde in document_changes:
            text_document = _field(tde, "textDocument", "text_document")
            tde_uri = _field(text_document, "uri")
            if tde_uri is not None and tde_uri != uri:
                continue
            text_edits = _field(tde, "edits")
            if text_edits:
                new_text = _field(text_edits[0], "newText", "new_text")
                if new_text is not None:
                    return new_text
        return None

    changes = _field(edits, "changes")
    if changes is None:
        return None

    if isinstance(changes, dict):
        # A real dict is URI-keyed: a missing requested URI means "no edit for
        # this file". Don't fall back to some other file's edit text.
        preferred = changes.get(uri)
        if preferred is None:
            return None
        edit_lists: list[Any] = [preferred]
    elif isinstance(changes, tuple):  # pygls Object (namedtuple of per-URI edit lists)
        edit_lists = list(changes)
    else:
        edit_lists = [getattr(changes, name) for name in getattr(changes, "_fields", ())]

    for text_edits in edit_lists:
        if text_edits:
            new_text = _field(text_edits[0], "newText", "new_text")
            if new_text is not None:
                return new_text
    return None
