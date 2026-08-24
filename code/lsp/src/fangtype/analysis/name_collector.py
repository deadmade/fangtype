"""AST visitor collecting Name nodes (definitions vs usages) for inlay hints."""

import ast
from dataclasses import dataclass

# NOTE: position_encoding imported lazily to break an analysis↔utils cycle; near-free after use.


@dataclass
class NameLocation:
    """Location of a Name node: name, 1-based line, code-point col/end_col, and is_definition."""

    name: str
    line: int
    col: int
    is_definition: bool
    end_col: int


class NameCollector(ast.NodeVisitor):
    """Record each Name as definition (Store) or usage (Load); skips annotations by default."""

    def __init__(
        self,
        skip_annotations: bool = True,
        include_expressions: bool = False,
        include_parameters: bool = False,
        source_lines: list[str] | None = None,
    ) -> None:
        """Flags gate annotation-skip, expr/param emit; source_lines→byte→cp cols (raw if None)."""
        self.names: list[NameLocation] = []
        self.skip_annotations = skip_annotations
        self.include_expressions = include_expressions
        self.include_parameters = include_parameters
        self._source_lines = source_lines
        self._in_annotation = False

    def _codepoint_col(self, lineno: int, byte_col: int) -> int:
        """Byte col on 1-based lineno → code-point col; raw offset if no source lines."""
        if self._source_lines is None or not (1 <= lineno <= len(self._source_lines)):
            return byte_col
        from fangtype.utils.position_encoding import byte_to_codepoint

        return byte_to_codepoint(self._source_lines[lineno - 1], byte_col)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """Visit annotated assignment (e.g. x: int = 5), skipping the annotation part."""
        # Visit the target (x)
        self.visit(node.target)

        # Skip the annotation (int) if configured
        if not self.skip_annotations:
            self._in_annotation = True
            self.visit(node.annotation)
            self._in_annotation = False

        # Visit the value (5) if present
        if node.value:
            self.visit(node.value)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Visit function definition, skipping annotations."""
        self._visit_function_def_impl(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Visit async function definition, skipping annotations."""
        self._visit_function_def_impl(node)

    def _visit_function_def_impl(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Implementation for visiting function definitions."""
        # Visit decorators
        for decorator in node.decorator_list:
            self.visit(decorator)

        # Visit arguments - skip annotations if configured
        args = node.args

        # Emit param bindings when enabled; flag-gated so inlay collectors stay unaffected.
        if self.include_parameters:
            for param in args.posonlyargs + args.args + args.kwonlyargs:
                self._record_arg(param)
            if args.vararg is not None:
                self._record_arg(args.vararg)
            if args.kwarg is not None:
                self._record_arg(args.kwarg)

        for arg in args.args + args.posonlyargs + args.kwonlyargs:
            if arg.annotation and not self.skip_annotations:
                self._in_annotation = True
                self.visit(arg.annotation)
                self._in_annotation = False

        # Visit defaults
        for default in args.defaults + args.kw_defaults:
            if default:
                self.visit(default)

        # Visit return annotation
        if node.returns and not self.skip_annotations:
            self._in_annotation = True
            self.visit(node.returns)
            self._in_annotation = False

        # Visit body
        for stmt in node.body:
            self.visit(stmt)

    def visit_Name(self, node: ast.Name) -> None:
        """Visit a Name node and record its location."""
        # Skip if we're inside an annotation and configured to skip
        if self._in_annotation:
            return

        is_definition = isinstance(node.ctx, ast.Store)
        col = self._codepoint_col(node.lineno, node.col_offset)
        end_col = col + len(node.id)

        self.names.append(
            NameLocation(
                name=node.id,
                line=node.lineno,  # 1-based
                col=col,  # 0-based, code points
                is_definition=is_definition,
                end_col=end_col,
            )
        )
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        """Record a whole subscript expression (e.g. ``bar[0]``), then recurse."""
        self._record_expression(node)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """Record a whole attribute expression (e.g. ``obj.attr``), then recurse."""
        self._record_expression(node)
        self.generic_visit(node)

    def _record_expression(self, node: ast.Subscript | ast.Attribute) -> None:
        """Emit a NameLocation for a subscript/attribute expression when enabled."""
        if not self.include_expressions or self._in_annotation:
            return

        is_definition = isinstance(node.ctx, ast.Store)
        col = self._codepoint_col(node.lineno, node.col_offset)
        if node.end_col_offset is not None:
            # end offset is on end_lineno (may differ for a multiline expression).
            end_col = self._codepoint_col(node.end_lineno or node.lineno, node.end_col_offset)
        else:
            end_col = col

        self.names.append(
            NameLocation(
                name=ast.unparse(node),
                line=node.lineno,  # 1-based
                col=col,  # 0-based, code points
                is_definition=is_definition,
                end_col=end_col,
            )
        )

    def _record_arg(self, arg: ast.arg) -> None:
        """Emit a NameLocation for a parameter binding (a definition)."""
        col = self._codepoint_col(arg.lineno, arg.col_offset)
        self.names.append(
            NameLocation(
                name=arg.arg,
                line=arg.lineno,  # 1-based
                col=col,  # 0-based, code points
                is_definition=True,
                end_col=col + len(arg.arg),
            )
        )

    @classmethod
    def collect_from_source(
        cls, source: str, include_expressions: bool = False
    ) -> list[NameLocation]:
        """Collect all name locations from source (optionally with subscript/attribute exprs)."""
        try:
            tree = ast.parse(source)
            from fangtype.utils.position_encoding import ast_source_lines

            collector = cls(
                include_expressions=include_expressions,
                source_lines=ast_source_lines(source),
            )
            collector.visit(tree)
            return collector.names
        except SyntaxError:
            return []

    @classmethod
    def collect_usages_only(
        cls, source: str, include_expressions: bool = False
    ) -> list[NameLocation]:
        """Collect only name usages (Load context, not definitions) from source code."""
        all_names = cls.collect_from_source(source, include_expressions=include_expressions)
        return [loc for loc in all_names if not loc.is_definition]

    @classmethod
    def collect_in_range(
        cls,
        source: str,
        start_line: int,
        end_line: int,
        buffer: int = 50,
        include_expressions: bool = False,
    ) -> list[NameLocation]:
        """Collect name usages within a 0-based LSP line range (plus buffer), for inlay hints."""
        all_names = cls.collect_usages_only(source, include_expressions=include_expressions)

        # Convert to 1-based for comparison with AST line numbers
        range_start = max(1, start_line + 1 - buffer)
        range_end = end_line + 1 + buffer

        return [loc for loc in all_names if range_start <= loc.line <= range_end]

    @classmethod
    def name_at_position(
        cls,
        source: str,
        line: int,
        character: int,
        *,
        include_expressions: bool = True,
        include_parameters: bool = True,
    ) -> NameLocation | None:
        """Jedi-free goto: NameLocation at cursor (1-based line, UTF-16 col) or None; defs first."""
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return None

        from fangtype.utils.position_encoding import ast_source_lines

        source_lines = ast_source_lines(source)
        collector = cls(
            include_expressions=include_expressions,
            include_parameters=include_parameters,
            source_lines=source_lines,
        )
        collector.visit(tree)

        # NameLocation columns are code points; the incoming LSP character is UTF-16.
        from fangtype.utils.position_encoding import utf16_to_codepoint

        line_text = source_lines[line - 1] if 1 <= line <= len(source_lines) else ""
        cp_character = utf16_to_codepoint(line_text, character)

        covering = [
            loc
            for loc in collector.names
            if loc.line == line and loc.col <= cp_character < loc.end_col
        ]
        if not covering:
            return None
        covering.sort(key=cls._position_selection_key)
        return covering[0]

    @staticmethod
    def _position_selection_key(loc: NameLocation) -> tuple[int, int, int]:
        """Rank overlapping names at cursor: defs, attr/subscript exprs, narrowest token."""
        is_expression = "." in loc.name or "[" in loc.name
        return (
            0 if loc.is_definition else 1,
            0 if is_expression else 1,
            loc.end_col - loc.col,
        )
