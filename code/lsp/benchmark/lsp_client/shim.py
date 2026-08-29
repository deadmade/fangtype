"""Lean scope-tree facade + LSP-backed shims for the benchmark runners.

The runners read a small, fixed slice of the inference `scope_tree`:
``get_variable_type_at_line``, ``get_function_scope_by_qualified_name`` (whose
result exposes ``return_type`` / ``parameters``), and
``get_attribute_type_for_method_context``. Rather than rebuild the real
``ScopeTree`` (which would mean replicating scope_builder's internals), these lean
classes answer exactly those queries from data scraped off LSP responses. They
reuse the real ``TypeInfo`` so ``.type_str`` reads are identical.
"""

from __future__ import annotations

import ast

from fangtype.analysis.types import TypeInfo, TypeSource
from fangtype.utils.position_encoding import ast_source_lines, byte_to_codepoint, codepoint_to_utf16


class LspScope:
    """A single function/method scope, populated from LSP responses."""

    def __init__(
        self,
        qualified_name: str,
        return_type: TypeInfo | None = None,
        parameters: dict[str, TypeInfo] | None = None,
        attributes: dict[str, TypeInfo] | None = None,
    ) -> None:
        self.qualified_name = qualified_name
        self.return_type = return_type
        self.parameters: dict[str, TypeInfo] = parameters or {}
        self.attributes: dict[str, TypeInfo] = attributes or {}


class LspScopeTree:
    """Minimal scope-tree facade answering the exact reads the runners perform."""

    def __init__(
        self,
        variables: dict[str, list[tuple[int, TypeInfo]]] | None = None,
        functions: dict[str, LspScope] | None = None,
        def_lines: dict[int, str] | None = None,
        func_ranges: dict[str, tuple[int, int]] | None = None,
    ) -> None:
        # name -> [(line0, TypeInfo), ...]
        self._variables: dict[str, list[tuple[int, TypeInfo]]] = variables or {}
        self._functions: dict[str, LspScope] = functions or {}
        # line0 -> dotted qualified name of the ``def`` on that line.
        self._def_lines: dict[int, str] = def_lines or {}
        # qualified name -> (start_line0, end_line0), inclusive.
        self._func_ranges: dict[str, tuple[int, int]] = func_ranges or {}

    def get_variable_type_at_line(self, name: str, line: int) -> TypeInfo | None:
        """Return the type of ``name`` assigned at ``line`` (0-based).

        Prefers an exact line match; if the name has exactly one typed assignment,
        returns it regardless of line (tolerates hint-position/line drift).
        """
        entries = self._variables.get(name)
        if not entries:
            return None
        for entry_line, info in entries:
            if entry_line == line:
                return info
        if len(entries) == 1:
            return entries[0][1]
        return None

    def get_function_scope_by_qualified_name(self, qualified_name: str) -> LspScope | None:
        return self._functions.get(qualified_name)

    def get_attribute_type_for_method_context(
        self, function_scope: LspScope | None, attr_name: str, line: int
    ) -> TypeInfo | None:
        """Return the type of ``attr_name`` in the given method scope (if known)."""
        if function_scope is None:
            return None
        return function_scope.attributes.get(attr_name)

    def get_all_function_scopes(self) -> list[LspScope]:
        return list(self._functions.values())

    def find_scope_for_line(self, line0: int) -> LspScope | None:
        """Return the INNERMOST function scope whose line range contains ``line0``
        (mirrors fangtype's ``ScopeTree.find_scope_for_line``). ``None`` at module level."""
        best_qname: str | None = None
        best_span: int | None = None
        for qname, (start, end) in self._func_ranges.items():
            if start <= line0 <= end:
                span = end - start
                if best_span is None or span < best_span:
                    best_span, best_qname = span, qname
        return self._functions.get(best_qname) if best_qname is not None else None

    def resolve_function_scope(
        self, function_name: str, line_number: int | None
    ) -> LspScope | None:
        """Resolve a scope from a *bare* function name + optional 1-based def line.

        Mirrors ``fangtype``'s ``type_recovery.resolve_function_scope``: prefer an
        exact def-line hit whose simple name matches, else the same-simple-name scope
        on the closest def line (tolerates decorator-line drift and same-named methods
        across classes), else an exact dotted-qname lookup.
        """
        simple = function_name.split(".")[-1]
        line0 = None if line_number is None else max(line_number - 1, 0)
        if line0 is not None:
            qname = self._def_lines.get(line0)
            if qname and qname.rsplit(".", 1)[-1] == simple:
                return self._functions.get(qname)
        candidates = [
            (line, qname)
            for line, qname in self._def_lines.items()
            if qname.rsplit(".", 1)[-1] == simple
        ]
        if candidates:
            if line0 is not None:
                _, qname = min(candidates, key=lambda item: abs(item[0] - line0))
            else:
                qname = candidates[0][1]
            return self._functions.get(qname)
        return self._functions.get(function_name)


def _ti(type_str: str, line: int) -> TypeInfo:
    return TypeInfo(type_str=type_str, source=TypeSource.UNKNOWN, line=line, col=0)


def _iter_targets(target: ast.expr) -> list[ast.expr]:
    """Flatten an assignment target into individual Name/Attribute nodes."""
    if isinstance(target, (ast.Tuple, ast.List)):
        out: list[ast.expr] = []
        for elt in target.elts:
            out.extend(_iter_targets(elt))
        return out
    return [target]


def _anchor_utf16(lines: list[str], line0: int, byte_col: int, extra_codepoints: int = 0) -> int:
    """Convert an ``ast`` byte column to the UTF-16 column an inlay hint would carry.

    Three encodings meet here. ``ast.col_offset``/``end_col_offset`` are UTF-8 **byte**
    offsets, the server computes a hint anchor in **code points** (``type_info.col +
    len(name)``), and it emits the anchor to the client in **UTF-16** code units. Comparing
    a raw byte column against a hint's character therefore silently mismatches on any line
    holding a non-ASCII character before the anchor, which would drop the hint as
    unresolvable rather than fail loudly. ``extra_codepoints`` is added in code-point space,
    mirroring the server's own ``+ len(name)``.
    """
    if not 0 <= line0 < len(lines):
        return byte_col + extra_codepoints
    line_text = lines[line0]
    return codepoint_to_utf16(line_text, byte_to_codepoint(line_text, byte_col) + extra_codepoints)


def _collect_structure(source: str):
    """Walk the AST once, mapping source lines to functions/params/attrs/vars.

    Returns (def_lines, param_pos, attr_lines, var_enclosing, def_params, func_ranges,
    attr_pos, name_pos):
      - def_lines: line0 -> qualified function name (of the ``def`` on that line)
      - param_pos: (line0, end_char) -> (qualified_name, param_name)
      - attr_lines: line0 -> (enclosing_qname, {attr names assigned via self.X})
      - var_enclosing: line0 -> enclosing function qname (or None at module level)
      - def_params: def-line0 -> {all param names of that def, incl self/cls and
        ``*args``/``**kwargs``}. A superset of ``param_pos``'s names, keyed by the ``def``
        line (where preview param entries land) so they can be filtered out of the
        variable bucket.
      - func_ranges: qualified_name -> (start_line0, end_line0), inclusive, spanning the
        whole ``def`` body (used to scope an attribute/line lookup to its enclosing method).
      - attr_pos: (line0, end_char) -> (enclosing_qname, bare_attr_name) for every
        ``self.x``-style store target
      - name_pos: (line0, end_char) -> (enclosing_qname_or_None, name) for every plain-name
        store target

    The three position maps share one key space, namely the UTF-16 column just past the end
    of the bound identifier, which is exactly where the server anchors a declaration hint
    (``type_info.col + len(name)``). ``ast`` hands that anchor over directly, because
    ``ast.Attribute.end_col_offset`` ends at the attribute name rather than at the whole
    ``self.width`` expression, so no arithmetic over the source text is needed.
    """
    def_lines: dict[int, str] = {}
    param_pos: dict[tuple[int, int], tuple[str, str]] = {}
    attr_lines: dict[int, tuple[str | None, set[str]]] = {}
    var_enclosing: dict[int, str | None] = {}
    def_params: dict[int, set[str]] = {}
    func_ranges: dict[str, tuple[int, int]] = {}
    attr_pos: dict[tuple[int, int], tuple[str | None, str]] = {}
    name_pos: dict[tuple[int, int], tuple[str | None, str]] = {}

    # ast_source_lines, never str.splitlines(): the tokenizer breaks lines only on \n, \r and
    # \r\n, while splitlines() also breaks on \v, \f, U+2028 and more, which would desync
    # these indices from node.lineno and convert every later column against the wrong line.
    lines = ast_source_lines(source)

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return (
            def_lines,
            param_pos,
            attr_lines,
            var_enclosing,
            def_params,
            func_ranges,
            attr_pos,
            name_pos,
        )

    def record_assignment(node: ast.AST, enclosing: str | None) -> None:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign, ast.NamedExpr, ast.For, ast.AsyncFor)):
            # AugAssign and NamedExpr bind a name just as the others do, and the ground
            # truth expects a ``function`` key on those facts. Without them ``n += 1`` and
            # ``(w := f())`` emit the right type on the right line with no enclosing
            # function, and the scorer matches on that key, so the fact never lands.
            # Caveat: a walrus in a def's default arg or decorator is visited with that
            # def's qname, though it really binds in the enclosing scope.
            targets = [node.target]
        for target in targets:
            for leaf in _iter_targets(target):
                if isinstance(leaf, ast.Attribute):
                    enc, names = attr_lines.get(leaf.lineno - 1, (enclosing, set()))
                    names.add(leaf.attr)
                    attr_lines[leaf.lineno - 1] = (enc, names)
                    if leaf.end_lineno is not None and leaf.end_col_offset is not None:
                        end = _anchor_utf16(lines, leaf.end_lineno - 1, leaf.end_col_offset)
                        attr_pos[(leaf.end_lineno - 1, end)] = (enclosing, leaf.attr)
                elif isinstance(leaf, ast.Name):
                    var_enclosing[leaf.lineno - 1] = enclosing
                    if leaf.end_lineno is not None and leaf.end_col_offset is not None:
                        end = _anchor_utf16(lines, leaf.end_lineno - 1, leaf.end_col_offset)
                        name_pos[(leaf.end_lineno - 1, end)] = (enclosing, leaf.id)

    def visit(node: ast.AST, prefix: str, enclosing_func: str | None) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qname = f"{prefix}.{child.name}" if prefix else child.name
                def_lines[child.lineno - 1] = qname
                end_lineno = child.end_lineno if child.end_lineno is not None else child.lineno
                func_ranges[qname] = (child.lineno - 1, end_lineno - 1)
                args = child.args
                names: set[str] = set()
                for arg in args.posonlyargs + args.args + args.kwonlyargs:
                    names.add(arg.arg)
                    if arg.arg == "self":
                        continue
                    # The server anchors a param hint at ``col + len(param_name)`` in code
                    # points, so the length is added in code-point space rather than taken
                    # from ``arg.end_col_offset`` (which would run past an annotation).
                    end = _anchor_utf16(lines, arg.lineno - 1, arg.col_offset, len(arg.arg))
                    param_pos[(arg.lineno - 1, end)] = (qname, arg.arg)
                for extra in (args.vararg, args.kwarg):
                    if extra is not None:
                        names.add(extra.arg)
                def_params[child.lineno - 1] = names
                visit(child, qname, qname)
            elif isinstance(child, ast.ClassDef):
                qname = f"{prefix}.{child.name}" if prefix else child.name
                visit(child, qname, enclosing_func)
            else:
                record_assignment(child, enclosing_func)
                visit(child, prefix, enclosing_func)

    visit(tree, "", None)
    return (
        def_lines,
        param_pos,
        attr_lines,
        var_enclosing,
        def_params,
        func_ranges,
        attr_pos,
        name_pos,
    )


def resolve_hint_facts(
    source: str, hints: list[tuple[int, int, str, bool]]
) -> tuple[list[tuple[str, str, int]], int]:
    """Resolve position-keyed inlay hints back to the name-keyed facts the runners score.

    Inlay hints are how the extension actually surfaces inference to a developer, so they
    are the honest fact source, but they carry a position and a rendered type and no name at
    all. Every declaration hint anchors just past the end of the identifier it annotates,
    which is the one property that makes the inverse mapping exact rather than a guess.

    Args:
        source: the document text the hints were produced for.
        hints: scraped inlay hints as ``(line0, char, type_str, is_return)``.

    Returns:
        ``(facts, dropped)``. ``facts`` is ``(name, type_str, line0)`` — deliberately the
        same shape ``_preview_tuples`` returns, so a consumer cannot tell which channel
        produced it. A parameter and a return both carry the ``def`` line, matching what
        ``previewInserts`` reported for them. ``dropped`` counts the hints that matched no
        store position, which is every usage-site hint (those sit at a Load position) plus a
        return on a wrapped signature, whose anchor is the closing-paren line.
    """
    (
        def_lines,
        param_pos,
        _attr_lines,
        _var_enclosing,
        _def_params,
        func_ranges,
        attr_pos,
        name_pos,
    ) = _collect_structure(source)

    facts: list[tuple[str, str, int]] = []
    dropped = 0
    for line0, char, type_str, is_return in hints:
        key = (line0, char)
        if is_return:
            qname = def_lines.get(line0)
            if qname is None:
                dropped += 1
                continue
            facts.append((qname.rsplit(".", 1)[-1], type_str, line0))
        elif key in param_pos:
            qname, param = param_pos[key]
            def_line0 = func_ranges.get(qname, (line0, line0))[0]
            facts.append((param, type_str, def_line0))
        elif key in attr_pos:
            facts.append((attr_pos[key][1], type_str, line0))
        elif key in name_pos:
            facts.append((name_pos[key][1], type_str, line0))
        else:
            dropped += 1
    return facts, dropped


def build_scope_tree(
    source: str,
    hints: list[tuple[int, int, str, bool]],
    preview: list[tuple[str, str, int]],
) -> LspScopeTree:
    """Assemble the facade from scraped inlay hints + previewInserts entries.

    Args:
        source: the (already-open) document text.
        hints: scraped inlay hints as ``(line0, char, type_str, is_return)``.
        preview: previewInserts entries as ``(name, type_str, line0)``.

    previewInserts is the primary source for variables/attributes/returns
    (name-keyed, unambiguous); inlay hints supply parameter types (position-matched
    to ``def`` param positions) and a return-type fallback.
    """
    (
        def_lines,
        param_pos,
        attr_lines,
        _var_enclosing,
        def_params,
        func_ranges,
        _attr_pos,
        _name_pos,
    ) = _collect_structure(source)

    variables: dict[str, list[tuple[int, TypeInfo]]] = {}
    functions: dict[str, LspScope] = {}

    def scope_for(qname: str) -> LspScope:
        if qname not in functions:
            functions[qname] = LspScope(qualified_name=qname)
        return functions[qname]

    for qname in def_lines.values():
        scope_for(qname)

    # Parameters + return fallback from inlay hints.
    for line0, char, type_str, is_return in hints:
        if is_return and line0 in def_lines:
            scope_for(def_lines[line0]).return_type = _ti(type_str, line0)
        elif (line0, char) in param_pos:
            qname, param = param_pos[(line0, char)]
            scope_for(qname).parameters[param] = _ti(type_str, line0)

    # Variables / attributes / returns from previewInserts (name-keyed).
    for name, type_str, line0 in preview:
        info = _ti(type_str, line0)
        if line0 in def_lines and def_lines[line0].rsplit(".", 1)[-1] == name:
            scope_for(def_lines[line0]).return_type = info
        elif name in def_params.get(line0, set()):
            # Parameter preview entry (sits on the ``def`` line) — parameters are
            # already recovered from inlay hints above; not a local variable.
            continue
        elif line0 in attr_lines and name in attr_lines[line0][1]:
            enclosing = attr_lines[line0][0]
            if enclosing is not None:
                scope_for(enclosing).attributes[name] = info
        else:
            variables.setdefault(name, []).append((line0, info))

    return LspScopeTree(
        variables=variables, functions=functions, def_lines=def_lines, func_ranges=func_ranges
    )


def resolve_inferred_type(
    tree: LspScopeTree,
    target_kind: str,
    line_number: int,
    variable_name: str | None,
    function_name: str | None,
    parameter_name: str | None,
) -> str | None:
    """Read a manifest target's inferred type from the LSP scope tree.

    Reads types straight off the facade (``previewInserts``/inlay hints): there are
    no engine recovery fallbacks (``infer_expression_type`` / ``recover_*`` /
    ``widen_optional``), so this returns ``None`` where the direct engine would have
    recovered a type. ``"Unknown"`` is treated as a miss.
    """
    line0 = max(line_number - 1, 0)

    if target_kind == "attribute":
        if variable_name is None:
            return None
        attr = variable_name.split(".")[-1]  # "self.x" -> "x"
        scope = tree.find_scope_for_line(line0)
        info = tree.get_attribute_type_for_method_context(scope, attr, line0)
        if info is not None and info.type_str != "Unknown":
            return info.type_str
        # Fall back to the old unscoped scan ONLY when no method encloses the line
        # (e.g. a class-body or module-level attribute) — never when a scope resolved,
        # so a same-named attr in an unrelated class can't spoof the result.
        if scope is None:
            for candidate in tree.get_all_function_scopes():
                other = candidate.attributes.get(attr)
                if other is not None and other.type_str != "Unknown":
                    return other.type_str
        info = tree.get_variable_type_at_line(attr, line0)
        return info.type_str if info is not None and info.type_str != "Unknown" else None

    if target_kind == "variable":
        if variable_name is None:
            return None
        info = tree.get_variable_type_at_line(variable_name, line0)
        return info.type_str if info is not None and info.type_str != "Unknown" else None

    if target_kind == "function_return":
        if not function_name:
            return None
        scope = tree.resolve_function_scope(function_name, line_number)
        if scope is not None and scope.return_type is not None:
            rt = scope.return_type.type_str
            return rt if rt != "Unknown" else None
        return None

    if target_kind == "function_param":
        if not function_name or not parameter_name:
            return None
        scope = tree.resolve_function_scope(function_name, line_number)
        if scope is not None:
            info = scope.parameters.get(parameter_name)
            if info is not None and info.type_str != "Unknown":
                return info.type_str
        return None

    return None


def is_valid_annotation(type_str: str | None) -> bool:
    """Whether ``type_str`` is a syntactically insertable type annotation.

    This mirrors the direct-path insertion outcome: LibCST inserts any syntactically
    valid annotation and only fails on malformed inference output (e.g. ``tuple[]`` or
    ``list[str]])``). It is deliberately per-target: the server's *bulk*
    ``insertTypesInFile`` is all-or-nothing — one malformed type aborts the whole
    file's insert — so it can't be used to judge each target independently.
    """
    if not type_str:
        return False
    try:
        ast.parse(f"__x: {type_str}", mode="exec")
        return True
    except SyntaxError:
        return False


# --- LSP-backed collection helpers ------------------------------------------

from benchmark.lsp_client.label_parse import (  # noqa: E402
    modified_source_from_edit,
    scrape_inlay_type,
)


def _hint_tuples(hints_raw: list) -> list[tuple[int, int, str, bool]]:
    out: list[tuple[int, int, str, bool]] = []
    for h in hints_raw:
        label = h.label
        text = (
            label if isinstance(label, str) else "".join(getattr(p, "value", str(p)) for p in label)
        )
        type_str = scrape_inlay_type(label)
        if type_str:
            out.append(
                (h.position.line, h.position.character, type_str, text.strip().startswith("->"))
            )
    return out


def _preview_tuples(preview_raw: object) -> list[tuple[str, str, int]]:
    will = getattr(preview_raw, "will_insert", None)
    if will is None and isinstance(preview_raw, dict):
        will = preview_raw.get("will_insert")
    out: list[tuple[str, str, int]] = []
    for entry in will or []:
        variable = (
            entry.get("variable") if isinstance(entry, dict) else getattr(entry, "variable", None)
        )
        type_str = entry.get("type") if isinstance(entry, dict) else getattr(entry, "type", None)
        line = entry.get("line") if isinstance(entry, dict) else getattr(entry, "line", None)
        if variable is not None and type_str is not None and line is not None:
            out.append((variable, type_str, line - 1))  # server line is 1-based
    return out


async def collect_document(
    client, uri: str, source: str, did_open: bool = False
) -> tuple[list, list]:
    """Gather inlay hints + previewInserts for a document.

    When ``did_open`` is False (inference mode, where the on-disk file already holds
    the exact source) the server reads the file from disk — we skip ``didOpen`` to
    avoid the per-open diagnostics scheduling that congests the server over a long
    run. When True (e.g. stripped mypy source) we sync the text via ``didOpen``.
    """
    if did_open:
        await client.open_document(uri, source)
    try:
        hints_raw = await client.inlay_hints(uri)
        preview_raw = await client.preview_inserts(uri)
    finally:
        if did_open:
            await client.close_document(uri)
    return _hint_tuples(hints_raw), _preview_tuples(preview_raw)


async def insert_all(client, uri: str) -> tuple[bool, str | None]:
    """Issue fangtype/insertTypesInFile; reconstruct the modified source from the WorkspaceEdit.

    Returns (success, modified_source). success is whether the server produced a full-document
    edit (i.e. at least one annotation was inserted); modified_source is None when nothing was
    inserted. Best-effort: a target the server can't infer is simply absent from the edit.
    """
    resp = await client.insert_types_in_file(uri)
    modified = modified_source_from_edit(resp, uri)
    return (modified is not None), modified


async def insert_document(client, uri: str, source: str) -> tuple[bool, str | None, dict[str, int]]:
    """Open a doc with ``source``, insert all inferred types, close it.

    The open→insert→close that ``collect_document`` (which closes the doc) and ``insert_all``
    (which never opens) don't provide together. Returns ``(success, modified_source,
    variable_drop_reasons)``: ``success`` is whether the server produced a full-document
    edit; ``modified_source`` is None when nothing was inserted; ``variable_drop_reasons``
    is the server's per-name miss-attribution histogram (empty when absent).
    """
    await client.open_document(uri, source)
    try:
        resp = await client.insert_types_in_file(uri)
        modified = modified_source_from_edit(resp, uri)
        return (modified is not None), modified, _drop_reasons_from_response(resp)
    finally:
        await client.close_document(uri)


def _drop_reasons_from_response(resp: object) -> dict[str, int]:
    """Pull the ``variable_drop_reasons`` histogram out of an insert response.

    pygls structures a server's freeform response dict into a **namedtuple-like** object
    (not a ``dict``), so the histogram arrives as a plain dict from test doubles but as a
    namedtuple (has ``_asdict``) from the live server — the earlier ``isinstance(resp,
    dict)`` guard silently dropped the live case. Absent/unrecognized → empty.
    """
    raw = (
        resp.get("variable_drop_reasons")
        if isinstance(resp, dict)
        else getattr(resp, "variable_drop_reasons", None)
    )
    if isinstance(raw, dict):
        return {str(k): int(v) for k, v in raw.items()}
    if raw is not None and hasattr(raw, "_asdict"):  # pygls namedtuple histogram structuring
        return {str(k): int(v) for k, v in raw._asdict().items()}
    return {}
