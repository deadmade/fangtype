"""Turn LSP inference signals into TypeEvalPy ground-truth-schema facts."""

from __future__ import annotations

from benchmark.lsp_client.shim import _collect_structure


def split_types(type_str: str) -> list[str]:
    """Split a type string on top-level PEP-604 ``|``, bracket-depth aware.

    Only splits ``|`` outside of ``[...]``, so ``"dict[str | int, int]"`` stays a
    single element while ``"int | None"`` becomes ``["int", "None"]``.
    ``Union[...]``/``Optional[...]``/subscripts/``None`` are left untouched --
    the submodule's own ``format_type`` normalizes those. Empty components (from
    stray whitespace) are dropped.
    """
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for char in type_str:
        if char in "[(":
            depth += 1
            current.append(char)
        elif char in "])":
            depth -= 1
            current.append(char)
        elif char == "|" and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return [p.strip() for p in parts if p.strip()]


def _is_meaningful(types: list[str]) -> bool:
    """Mirrors jedi's ``if _type: append`` -- drop empty or sole-``Unknown`` types."""
    return bool(types) and types != ["Unknown"]


def emit_facts(
    source: str,
    hints: list[tuple[int, int, str, bool]],
    preview: list[tuple[str, str, int]],
    *,
    filename: str,
) -> list[dict]:
    """Emit TypeEvalPy ground-truth-schema facts from scraped LSP signals.

    Args:
        source: the document text (used to recover def/param/attribute structure).
        hints: scraped inlay hints as ``(line0, char, type_str, is_return)``.
        preview: previewInserts entries as ``(name, type_str, line0)``.
        filename: the ``"file"`` value to stamp on every emitted fact.

    Returns:
        A list of fact dicts. Every fact has ``"file"``, 1-based ``"line_number"``,
        and a non-empty, non-``["Unknown"]`` ``"type"`` list, plus exactly one
        discriminator (``"parameter"`` + ``"function"`` for params, ``"function"``
        alone for returns, ``"variable"`` (``"self.x"``) + ``"function"`` for
        attributes, ``"variable"`` (+ ``"function"`` when in-function) for locals).
        No ``"col_offset"`` is emitted -- see ``official.py`` for why.
    """
    def_lines, param_pos, attr_lines, var_enclosing, def_params, _func_ranges = _collect_structure(
        source
    )

    facts: list[dict] = []
    # (line0, function qname) -> type_str. Hints populate this first; a matching
    # preview return signal unconditionally overwrites it (preview runs second and
    # wins), mirroring build_scope_tree's own "preview overwrites hint" precedence.
    # Facts are only materialized (and Unknown/empty-filtered) once, at the end, so
    # a def with both a hint and a preview signal yields exactly one return fact.
    return_type_str: dict[tuple[int, str], str] = {}

    # Parameters + return fallback from inlay hints.
    for line0, char, type_str, is_return in hints:
        if is_return and line0 in def_lines:
            return_type_str[(line0, def_lines[line0])] = type_str
        elif (line0, char) in param_pos:
            qname, param = param_pos[(line0, char)]
            types = split_types(type_str)
            if _is_meaningful(types):
                facts.append(
                    {
                        "file": filename,
                        "line_number": line0 + 1,
                        "function": qname,
                        "parameter": param,
                        "type": types,
                    }
                )

    # Returns / attributes / locals from previewInserts (name-keyed).
    for name, type_str, line0 in preview:
        if line0 in def_lines and def_lines[line0].rsplit(".", 1)[-1] == name:
            return_type_str[(line0, def_lines[line0])] = type_str
            continue

        if name in def_params.get(line0, set()):
            # Parameter preview entry (sits on the ``def`` line) — parameters are
            # emitted from inlay hints above; not a local variable. Skip so it does
            # not pollute the local_variables bucket.
            continue

        # ``_collect_structure`` keys attributes by their bare name (``"width"``); the
        # server may report either the bare name or the dotted access (``"self.width"``).
        # Match on the bare tail, emit the dotted variable the ground truth expects.
        bare_attr = name.rsplit(".", 1)[-1]
        if line0 in attr_lines and bare_attr in attr_lines[line0][1]:
            enclosing = attr_lines[line0][0]
            if enclosing is not None:
                types = split_types(type_str)
                if _is_meaningful(types):
                    facts.append(
                        {
                            "file": filename,
                            "line_number": line0 + 1,
                            "function": enclosing,
                            "variable": name if "." in name else f"self.{name}",
                            "type": types,
                        }
                    )
            continue

        # Local / module-level variable. Cannot emit subscript facts (data[0],
        # d['k']) -- fangtype produces no signal keyed by subscript expression, so
        # those ground-truth entries stay honest recall misses rather than being
        # synthesized here.
        types = split_types(type_str)
        if not _is_meaningful(types):
            continue
        fact: dict = {"file": filename, "line_number": line0 + 1, "variable": name, "type": types}
        enclosing = var_enclosing.get(line0)
        if enclosing is not None:
            fact["function"] = enclosing
        facts.append(fact)

    for (line0, function), type_str in return_type_str.items():
        types = split_types(type_str)
        if not _is_meaningful(types):
            continue
        facts.append(
            {
                "file": filename,
                "line_number": line0 + 1,
                "function": function,
                "type": types,
            }
        )

    return facts
