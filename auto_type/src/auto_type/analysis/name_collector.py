"""AST Name Collector for finding all name usages in Python source code.

This module provides a class that traverses Python AST to collect all Name nodes,
distinguishing between definitions (Store context) and usages (Load context).
Used for generating inlay hints at variable usage sites.
"""

import ast
from dataclasses import dataclass


@dataclass
class NameLocation:
    """Location of a Name node in source code.

    Attributes:
        name: The identifier name
        line: 1-based line number (matches Jedi convention)
        col: 0-based column offset
        is_definition: True if this is a definition (Store), False if usage (Load)
        end_col: Column offset after the identifier ends
    """

    name: str
    line: int
    col: int
    is_definition: bool
    end_col: int


class NameCollector(ast.NodeVisitor):
    """Collects all Name nodes from Python AST.

    This visitor traverses the AST and records every Name node, tracking whether
    each occurrence is a definition (assignment target) or a usage (reference).
    By default, it skips names that appear in type annotation contexts.

    Usage:
        collector = NameCollector()
        collector.visit(ast.parse(source))
        locations = collector.names
    """

    def __init__(self, skip_annotations: bool = True) -> None:
        """Initialize the collector with empty name list.

        Args:
            skip_annotations: If True, skip names in type annotation positions
        """
        self.names: list[NameLocation] = []
        self.skip_annotations = skip_annotations
        self._in_annotation = False

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """Visit annotated assignment, skipping the annotation part.

        Args:
            node: AST AnnAssign node (e.g., x: int = 5)
        """
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
        """Visit function definition, skipping annotations.

        Args:
            node: AST FunctionDef node
        """
        self._visit_function_def_impl(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Visit async function definition, skipping annotations.

        Args:
            node: AST AsyncFunctionDef node
        """
        self._visit_function_def_impl(node)

    def _visit_function_def_impl(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Implementation for visiting function definitions.

        Args:
            node: AST function definition node
        """
        # Visit decorators
        for decorator in node.decorator_list:
            self.visit(decorator)

        # Visit arguments - skip annotations if configured
        args = node.args
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
        """Visit a Name node and record its location.

        Args:
            node: AST Name node to process
        """
        # Skip if we're inside an annotation and configured to skip
        if self._in_annotation:
            return

        is_definition = isinstance(node.ctx, ast.Store)
        end_col = node.col_offset + len(node.id)

        self.names.append(
            NameLocation(
                name=node.id,
                line=node.lineno,  # 1-based
                col=node.col_offset,  # 0-based
                is_definition=is_definition,
                end_col=end_col,
            )
        )
        self.generic_visit(node)

    @classmethod
    def collect_from_source(cls, source: str) -> list[NameLocation]:
        """Collect all name locations from source code.

        Args:
            source: Python source code string

        Returns:
            List of NameLocation objects for all names in the source
        """
        try:
            tree = ast.parse(source)
            collector = cls()
            collector.visit(tree)
            return collector.names
        except SyntaxError:
            return []

    @classmethod
    def collect_usages_only(cls, source: str) -> list[NameLocation]:
        """Collect only name usages (not definitions) from source code.

        This is a convenience method that filters out definitions, returning
        only Load context names which are candidates for usage-site type hints.

        Args:
            source: Python source code string

        Returns:
            List of NameLocation objects for name usages only
        """
        all_names = cls.collect_from_source(source)
        return [loc for loc in all_names if not loc.is_definition]

    @classmethod
    def collect_in_range(
        cls,
        source: str,
        start_line: int,
        end_line: int,
        buffer: int = 50,
    ) -> list[NameLocation]:
        """Collect name usages within a line range (with buffer).

        Optimized for LSP inlay hints where only the visible range matters.

        Args:
            source: Python source code string
            start_line: Start line (0-based, LSP convention)
            end_line: End line (0-based, LSP convention)
            buffer: Extra lines to include around the range for smooth scrolling

        Returns:
            List of NameLocation objects for usages in the range
        """
        all_names = cls.collect_usages_only(source)

        # Convert to 1-based for comparison with AST line numbers
        range_start = max(1, start_line + 1 - buffer)
        range_end = end_line + 1 + buffer

        return [loc for loc in all_names if range_start <= loc.line <= range_end]
