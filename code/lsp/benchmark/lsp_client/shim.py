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
import logging
import tokenize
from typing import TYPE_CHECKING

from fangtype.analysis.ast_traversal import is_implicit_receiver
from fangtype.analysis.types import TypeInfo, TypeSource
from fangtype.utils.position_encoding import ast_source_lines, byte_to_codepoint, codepoint_to_utf16

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


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


def innermost_enclosing_func(line0: int, func_ranges: dict[str, tuple[int, int]]) -> str | None:
    """Return the qualified name of the INNERMOST function whose range contains ``line0``.

    ``func_ranges`` maps a qualified name to its ``(start_line0, end_line0)`` span, inclusive,
    and a nested ``def`` sits entirely inside every one of its enclosing ``def``s' ranges, so a
    line inside the nested body matches more than one entry. The smallest span always belongs
    to the innermost function, since an outer function's range strictly contains every nested
    one, so picking the minimum span rather than the first hit is what keeps a return on a
    nested function from being attributed to its parent. ``None`` when no range contains the
    line, i.e. at module level.

    This is the one selection rule shared by ``LspScopeTree.find_scope_for_line`` and the
    return-hint recovery in ``resolve_hint_facts``/``fact_emitter.emit_facts`` below, so all
    three treat a wrapped or nested signature the same way.
    """
    best_qname: str | None = None
    best_span: int | None = None
    for qname, (start, end) in func_ranges.items():
        if start <= line0 <= end:
            span = end - start
            if best_span is None or span < best_span:
                best_span, best_qname = span, qname
    return best_qname


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
        qname = innermost_enclosing_func(line0, self._func_ranges)
        return self._functions.get(qname) if qname is not None else None

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
    if isinstance(target, ast.Starred):
        # ``*rest`` binds ``rest``, and the server anchors its hint on the name inside the
        # star rather than on the star. Left unwrapped, the ``Starred`` node reached neither
        # the ``Name`` branch nor the ``Attribute`` branch below and the binding vanished.
        return _iter_targets(target.value)
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


def _codepoint_col(lines: list[str], line0: int, byte_col: int) -> int:
    """An ``ast`` UTF-8 byte column as a code-point index, passed through for a missing line."""
    if not 0 <= line0 < len(lines):
        return byte_col
    return byte_to_codepoint(lines[line0], byte_col)


def _except_name_anchors(
    lines: list[str], tree: ast.Module
) -> dict[tuple[int, int], tuple[int, int]]:
    """Locate the bound identifier of every named ``except`` handler by tokenizing.

    ``ast.ExceptHandler.name`` is a bare ``str`` rather than a node, so alone among the
    binding forms this module records it carries no position and the anchor has to be
    recovered from the source text. The grammar makes that recovery exact rather than a
    guess. A handler that binds a name must also carry a type, because ``except as e:``
    does not parse, and between the end of that type and the start of the handler's first
    statement the grammar admits nothing but ``as NAME``, whitespace, backslash
    continuations and the colon. A comment cannot sit in that span either, since a comment
    ends the logical line and only a backslash or an open bracket continues one, and a
    backslash has to be the last character on its line.

    So each handler's span is searched for the one ``as NAME`` token pair whose name is the
    handler's, and a handler yielding anything other than exactly one match is left out of
    the map entirely. Its hint then falls through to ``resolve_hint_facts``'s drop counter,
    which is the outcome to prefer over resolving a fact onto the wrong name.

    Returns ``{(handler_line0, handler_byte_col): (name_line0, name_end_utf16_col)}``. The
    key is the handler's own start position, which is unique because two handlers cannot
    begin at the same one, and the value is in the same UTF-16 key space as ``name_pos``.
    """
    handlers = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ExceptHandler)
        and node.name is not None
        and node.type is not None
        and node.body
    ]
    if not handlers:
        return {}

    # Tokenized over exactly the partition ``ast_source_lines`` produced, never over
    # ``source`` directly, so a token's line index and the ``ast`` line indices compared
    # against it below cannot disagree about which line is which.
    line_iter = iter([f"{line}\n" for line in lines])

    def readline() -> str:
        return next(line_iter, "")

    as_names: list[tuple[int, int, int, str]] = []
    try:
        after_as = False
        for token in tokenize.generate_tokens(readline):
            if after_as and token.type == tokenize.NAME:
                as_names.append((token.start[0] - 1, token.start[1], token.end[1], token.string))
            after_as = token.type == tokenize.NAME and token.string == "as"
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return {}

    anchors: dict[tuple[int, int], tuple[int, int]] = {}
    for handler in handlers:
        type_node = handler.type
        if type_node is None or type_node.end_lineno is None or type_node.end_col_offset is None:
            continue
        after_type = (
            type_node.end_lineno - 1,
            _codepoint_col(lines, type_node.end_lineno - 1, type_node.end_col_offset),
        )
        first_stmt = handler.body[0]
        before_body = (
            first_stmt.lineno - 1,
            _codepoint_col(lines, first_stmt.lineno - 1, first_stmt.col_offset),
        )
        matches = [
            (line0, end_col)
            for line0, start_col, end_col, name in as_names
            if name == handler.name
            and after_type <= (line0, start_col)
            and (line0, end_col) <= before_body
        ]
        if len(matches) != 1:
            continue
        line0, end_col = matches[0]
        anchors[(handler.lineno - 1, handler.col_offset)] = (
            line0,
            codepoint_to_utf16(lines[line0], end_col),
        )
    return anchors


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
        line, where a parameter's name-keyed fact lands, so they can be filtered out of
        the variable bucket.
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

    Every binding form the server draws a hint on has to be recorded here, because a form
    that is missing is not a visible failure: its hints simply match no position, and
    ``resolve_hint_facts`` counts them as drops alongside the usage-site hints it is meant
    to drop. ``with`` items, ``except`` handlers and comprehension targets were exactly that
    for a while, and the server emits ``_IOBase`` for ``with io.StringIO() as fh``,
    ``ValueError`` for ``except ValueError as err`` and ``int`` for the ``q`` of
    ``[q for q in range(3)]``. The starred half of ``a, *rest = ...`` was the fourth, and
    it is why ``_iter_targets`` unwraps ``ast.Starred``, since the server draws
    ``list[int]`` at the anchor past ``rest``. Two forms the server draws nothing on are
    deliberately absent instead, namely ``import x as y`` and a ``match`` capture pattern.
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

    except_anchors = _except_name_anchors(lines, tree)

    def record_assignment(node: ast.AST, enclosing: str | None) -> None:
        if isinstance(node, ast.ExceptHandler):
            # The only binding form here whose name is a plain ``str`` with no position of
            # its own, so its anchor comes from the tokenizing pass above. A handler that
            # pass could not place unambiguously is absent from the map, and leaving its
            # hint to the drop counter is the point rather than a shortfall.
            if node.name is not None:
                anchor = except_anchors.get((node.lineno - 1, node.col_offset))
                if anchor is not None:
                    var_enclosing[anchor[0]] = enclosing
                    name_pos[anchor] = (enclosing, node.name)
            return
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.withitem):
            # ``with open(p) as fh`` and ``with open(p) as self.fh`` both bind, and
            # ``optional_vars`` is an ``expr`` (a ``Name``, an ``Attribute``, or a ``Tuple``
            # for ``as (x, y)``), so it needs no handling of its own past this unwrapping.
            if node.optional_vars is not None:
                targets = [node.optional_vars]
        elif isinstance(
            node,
            (
                ast.AnnAssign,
                ast.AugAssign,
                ast.NamedExpr,
                ast.For,
                ast.AsyncFor,
                ast.comprehension,
            ),
        ):
            # AugAssign and NamedExpr bind a name just as the others do, and the ground
            # truth expects a ``function`` key on those facts. Without them ``n += 1`` and
            # ``(w := f())`` emit the right type on the right line with no enclosing
            # function, and the scorer matches on that key, so the fact never lands.
            # Caveat: a walrus in a def's default arg or decorator is visited with that
            # def's qname, though it really binds in the enclosing scope.
            # A comprehension target is attributed to the enclosing ``def`` for the same
            # reason it has to be here at all, namely that the server files it in that
            # def's ``Scope`` rather than in a scope of the comprehension's own.
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

    def visit(node: ast.AST, prefix: str, enclosing_func: str | None, in_class: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qname = f"{prefix}.{child.name}" if prefix else child.name
                def_lines[child.lineno - 1] = qname
                end_lineno = child.end_lineno if child.end_lineno is not None else child.lineno
                func_ranges[qname] = (child.lineno - 1, end_lineno - 1)
                args = child.args
                names: set[str] = set()
                # ``vararg``/``kwarg`` belong in this loop and not merely in ``names``.
                # ``scope.parameters`` carries them, so the server draws a hint on
                # ``*integers`` and on ``**kwargs``, and TypeEvalPy's ground truth asks for
                # both by their bare names. Keyed off them only for ``def_params``, those
                # two hints matched no position and left as drops.
                for arg in (
                    *args.posonlyargs,
                    *args.args,
                    *args.kwonlyargs,
                    args.vararg,
                    args.kwarg,
                ):
                    if arg is None:
                        continue
                    names.add(arg.arg)
                    # The server's own predicate, not a match on the name. It is positional
                    # and class-aware, so a parameter merely called ``self`` in a
                    # module-level function or a ``staticmethod`` is a real parameter and
                    # the server draws a hint on it. Skipping by name alone dropped twelve
                    # such hints in the mypy corpus's own ``exportjson.py``, whose
                    # ``convert_*`` functions are free functions with a ``self`` parameter.
                    if is_implicit_receiver(child, arg.arg, in_class=in_class):
                        continue
                    # The server anchors a param hint at ``col + len(param_name)`` in code
                    # points, so the length is added in code-point space rather than taken
                    # from ``arg.end_col_offset`` (which would run past an annotation).
                    # ``ast.arg.col_offset`` starts at the identifier rather than at the
                    # stars of a ``*``/``**`` parameter, which is where the server's own
                    # ``type_info.col`` starts too.
                    end = _anchor_utf16(lines, arg.lineno - 1, arg.col_offset, len(arg.arg))
                    param_pos[(arg.lineno - 1, end)] = (qname, arg.arg)
                def_params[child.lineno - 1] = names
                visit(child, qname, qname, in_class=False)
            elif isinstance(child, ast.ClassDef):
                qname = f"{prefix}.{child.name}" if prefix else child.name
                visit(child, qname, enclosing_func, in_class=True)
            else:
                record_assignment(child, enclosing_func)
                # ``in_class`` carries through a plain statement, because a ``def`` under an
                # ``if`` in a class body is still a method whose parent scope is the class.
                visit(child, prefix, enclosing_func, in_class=in_class)

    visit(tree, "", None, in_class=False)
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
        same shape the retired ``previewInserts`` scrape returned, so a consumer cannot tell
        which channel produced it. A parameter and a return both carry the ``def`` line,
        matching what ``previewInserts`` reported for them, even when the return hint itself
        anchors on a wrapped signature's closing-paren line (see the ``is_return`` branch).
        ``dropped`` counts the hints that matched no store position, which is every
        usage-site hint (those sit at a Load position).
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
            # A single-line def anchors its return hint on the def line itself, so the
            # exact hit resolves for free. A wrapped def anchors on the closing-paren line
            # instead (`_signature_end`), which is never a `def_lines` key, so that case
            # falls through to the innermost function enclosing the hint's line — the same
            # rule `find_scope_for_line` uses, picked by minimum span so a nested def's
            # return is never misattributed to the def that contains it.
            qname = def_lines.get(line0)
            if qname is None:
                qname = innermost_enclosing_func(line0, func_ranges)
            if qname is None:
                dropped += 1
                continue
            def_line0 = func_ranges.get(qname, (line0, line0))[0]
            facts.append((qname.rsplit(".", 1)[-1], type_str, def_line0))
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
    name_facts: list[tuple[str, str, int]],
) -> LspScopeTree:
    """Assemble the facade from scraped inlay hints + the name-keyed facts resolved from them.

    Args:
        source: the (already-open) document text.
        hints: scraped inlay hints as ``(line0, char, type_str, is_return)``.
        name_facts: name-keyed facts as ``(name, type_str, line0)``, as ``resolve_hint_facts``
            returns them. The shape is identical to the one ``previewInserts`` used to
            produce, which is why this function did not move when the producer did.

    The name-keyed facts are the source for variables/attributes/returns (unambiguous once
    a name is attached); the raw hints supply parameter types (position-matched to ``def``
    param positions) and a return-type fallback. Both halves now come from the same
    ``textDocument/inlayHint`` answer, so the two loops below agree by construction where
    they used to be two channels that could disagree.
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

    # Variables / attributes / returns from the name-keyed facts.
    for name, type_str, line0 in name_facts:
        info = _ti(type_str, line0)
        if line0 in def_lines and def_lines[line0].rsplit(".", 1)[-1] == name:
            scope_for(def_lines[line0]).return_type = info
        elif name in def_params.get(line0, set()):
            # Parameter fact (sits on the ``def`` line) — parameters are
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

    Reads types straight off the facade, which now carries only what the inlay hints said.
    There are no engine recovery fallbacks (``infer_expression_type`` / ``recover_*`` /
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


async def collect_document(
    client,
    uri: str,
    source: str,
    did_open: bool = False,
    on_dropped: Callable[[int], None] | None = None,
) -> tuple[list, list]:
    """Gather inlay hints for a document and resolve them into name-keyed facts.

    One request goes out, ``textDocument/inlayHint``, and both halves of the return are
    derived from its answer. The harness used to ask ``fangtype/previewInserts`` for the
    second half, a custom request the shipped extension never sends and this harness was
    the only caller of, so the benchmark scored a channel no developer is ever served by.
    ``resolve_hint_facts`` inverts each hint's anchor back to the binding it annotates and
    produces the same ``(name, type_str, line0)`` shape, which is why the runners that
    unpack this tuple did not have to move.

    When ``did_open`` is False (inference mode, where the on-disk file already holds
    the exact source) the server reads the file from disk — we skip ``didOpen`` to
    avoid the per-open diagnostics scheduling that congests the server over a long
    run. When True (e.g. stripped mypy source) we sync the text via ``didOpen``.

    ``resolve_hint_facts`` also reports how many hints matched no binding, which is every
    usage-site hint plus anything whose anchor the inverse mapping cannot place. That count
    cannot ride along in the return, because four runners plus the bridge's cache depend on
    the two-element shape, and it must not simply vanish either — a drop that nobody counts
    is a moved evaluation number with no cause attached to it. It therefore leaves by two
    other routes, namely a DEBUG log line per document for locality when one file looks
    wrong, and ``on_dropped``, which ``ClientBridge`` uses to accumulate a run-wide total a
    runner can read once at the end. ``on_dropped`` is called for every document, including
    the ones that drop nothing, so the total is a sum over the whole run rather than over
    the subset that happened to lose something.

    The two channels do not admit the same set, so a later accounting of moved evaluation
    numbers has named causes to work from rather than an unexplained delta. Facts are gained
    on ``global``/``nonlocal`` names, which ``_binding_is_insertable`` filtered out of the
    insert path and which ``generate_hints_for_scope`` does not filter. Facts are gained on
    comprehension targets for the same shape of reason, because ``_binding_is_insertable``
    also rejects any binding whose position sits in ``comprehension_target_positions`` and
    the hint path consults no such set. And facts are gained wherever LibCST could not have
    placed the annotation at all, because ``preview_insertions`` in the insertion engine
    discards the ``failures`` half of ``_create_execution_plans`` and keeps only ``plans``,
    so a target whose type ``sanitize_type_annotation`` cannot salvage into valid syntax was
    silently absent from ``will_insert`` and is present here.

    A fourth cause stood here until the display caught up with the write path. Facts were
    lost per binding, because ``Scope.variables`` collapses a name's history to ``types[-1]``
    and the server drew one hint per name per scope where ``previewInserts`` reported every
    binding. ``generate_hints_for_scope`` iterates ``variable_history`` now, so that loss is
    gone, and it is named here only because the branch's own commit messages still carry the
    old wording and a reader meeting it needs to know which of the two is current.

    That last one is where a reader is most likely to go wrong, so it is worth being exact
    about what it is not. **Neither channel ever ran mypy.** ``preview_insertions`` in the
    workflow passes ``per_binding=True``, which makes ``best_valid`` False, which leaves
    ``validated_vars`` as ``None`` and builds targets from the raw inferred insertions. The
    type validator is reached from exactly one place in that file, inside
    ``_insert_with_assignability_gate``, which the preview path never calls. The naming
    along that path is what misleads — a local called ``validated_vars`` and an early return
    reading "all types failed validation" both sit on a branch where no validation happened.
    The gate is real, but it belongs to insertion, so it never filtered the fact set on
    either side of this change and it is not a cause of any number that moves.
    """
    if did_open:
        await client.open_document(uri, source)
    try:
        hints_raw = await client.inlay_hints(uri)
    finally:
        if did_open:
            await client.close_document(uri)
    hints = _hint_tuples(hints_raw)
    facts, dropped = resolve_hint_facts(source, hints)
    if dropped:
        logger.debug("%s: %d inlay hint(s) resolved to no binding", uri, dropped)
    if on_dropped is not None:
        on_dropped(dropped)
    return hints, facts


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
