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


def as_mapping(entry: Any) -> dict[str, Any]:
    """Normalise one removal-record-shaped entry to a plain ``dict``.

    ``RemovalRecord`` (``removal/engine.py``) is a ``TypedDict`` and serialises to a
    plain JSON object, but pygls re-parses every custom-request response through
    ``pygls.protocol._dict_to_object``, whose ``object_hook`` turns each nested object
    into ``namedtuple(type_name, keys, rename=True)(*values)`` rather than leaving it a
    ``dict``. A caller that reads ``entry["type"]`` off that namedtuple gets
    ``TypeError: tuple indices must be integers or slices, not str``, because subscripting
    a tuple by name is not a thing. So a live response's entries need converting back to a
    mapping before any ``entry["..."]`` or ``entry.get("...")`` read is safe, exactly the
    concern ``_field`` above already handles for the single-key case.

    A plain ``dict`` (JSON, or a hand-built test double) passes through unchanged. An
    object exposing ``_asdict`` (the pygls namedtuple case) is converted through it, which
    also preserves ``None`` values for optional fields such as ``function_name`` and
    ``parameter_name``. Anything else raises rather than degrading to ``{}``, because a
    silently empty mapping would make every read below default or KeyError instead of
    surfacing that the wire shape changed, and a run that swallows 143 corpus files that
    way caches the resulting empty manifest and keeps reusing it.
    """
    if isinstance(entry, dict):
        return entry
    if hasattr(entry, "_asdict"):  # pygls namedtuple structuring of a JSON object
        return dict(entry._asdict())
    raise TypeError(
        f"as_mapping: expected a dict or an object with _asdict, got {type(entry).__name__}"
    )


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
