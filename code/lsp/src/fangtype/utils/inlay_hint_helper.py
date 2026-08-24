from __future__ import annotations

import ast
import asyncio
import io
import logging
import textwrap
import time
import tokenize
from typing import TYPE_CHECKING

from injector import inject
from lsprotocol import types

from fangtype.analysis import NameCollector, NameLocation, ScopeType, is_implicit_receiver
from fangtype.protocols import InferenceEngineProtocol  # noqa: TC001
from fangtype.utils.position_encoding import codepoint_to_utf16
from fangtype.utils.settings import Settings  # noqa: TC001

if TYPE_CHECKING:
    from fangtype.analysis import Scope, ScopeTree
    from fangtype.cancellation import CancellationToken
    from fangtype.inference.inference_result import InferenceResult
    from fangtype.validation.mypy_validator import TypeValidationResult

logger = logging.getLogger(__name__)


def _signature_end(
    source_lines: list[str], func_node: ast.FunctionDef | ast.AsyncFunctionDef
) -> tuple[int, int] | None:
    """(row_0based, codepoint col) just after a signature's closing ')', or None.

    Tokenizes only the signature, so a ')' in a trailing comment or a string default cannot be
    mistaken for it and a wrapped signature resolves to its real closing line.
    """
    start = func_node.lineno - 1
    if start >= len(source_lines) or not func_node.body:
        return None
    block = source_lines[start : func_node.body[0].lineno]
    if not block:
        return None
    # tokenize rejects a leading indent, so dedent first and re-add whatever it stripped. Measure
    # the strip rather than assuming the def's indent: a continuation line may be indented less.
    chunk = textwrap.dedent("".join(f"{line}\n" for line in block))
    stripped = len(block[0]) - len(chunk.split("\n", 1)[0])

    depth = 0
    try:
        for tok in tokenize.generate_tokens(io.StringIO(chunk).readline):
            if tok.exact_type == tokenize.LPAR:
                depth += 1
            elif tok.exact_type == tokenize.RPAR:
                depth -= 1
                if depth == 0:
                    row, col = tok.end
                    return start + row - 1, col + stripped
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return None
    return None


class InlayHintHelper:
    """Helper for generating inlay hints (some methods stay async for validation/LSP work)."""

    # injector's @inject leaks Any (overloads resolve to Any), so mypy's disallow_any_expr flags it.
    @inject  # type: ignore[misc]
    def __init__(
        self,
        name_collector: NameCollector,
        inference_engine: InferenceEngineProtocol,
        settings: Settings,
    ) -> None:
        self.name_collector = name_collector
        self.inference_engine = inference_engine
        self.settings = settings

    @staticmethod
    def _col_to_utf16(lines: list[str], line_index: int, cp_col: int) -> int:
        """Convert a 0-based code-point column to a UTF-16 column for LSP; pass through if OOB."""
        if 0 <= line_index < len(lines):
            return codepoint_to_utf16(lines[line_index], cp_col)
        return cp_col

    def _build_type_hint(
        self, line: int, char: int, separator: str, type_str: str, is_valid: bool
    ) -> types.InlayHint:
        """Build an InlayHint for a variable/parameter/return type, reflecting mypy validity."""
        if is_valid:
            label = f"{separator}{type_str}"
            tooltip = None
        else:
            label = f"{separator}⚠️ {type_str}"
            tooltip = "Type validation failed"

        return types.InlayHint(
            position=types.Position(line=line, character=char),
            label=label,
            kind=types.InlayHintKind.Type,
            padding_left=False,
            padding_right=False,
            tooltip=tooltip,
        )

    def get_annotated_variable_names(self, scope: Scope) -> set[str]:
        """Get names of variables with explicit type annotations (ast.AnnAssign) in a scope."""
        annotated_vars: set[str] = set()

        # Hand-rolled walk, not ast.walk: nested defs own their scope, and ast.walk descends into
        # them regardless of what the loop body does, leaking their annotations into this scope.
        stack: list[ast.AST] = list(ast.iter_child_nodes(scope.ast_node))
        while stack:
            node = stack.pop()
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue

            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                annotated_vars.add(node.target.id)

            stack.extend(ast.iter_child_nodes(node))

        return annotated_vars

    @staticmethod
    def _validity_for(
        validation_results: dict[str, TypeValidationResult] | None, validation_key: str
    ) -> bool | None:
        """Return key validity: None = don't emit; None results-dict = validation off, all valid."""
        if validation_results is None:
            return True
        result = validation_results.get(validation_key)
        return result.is_valid if result is not None else None

    def generate_hints_for_scope(
        self,
        scope: Scope,
        source: str,
        validation_results: dict[str, TypeValidationResult] | None,
        scope_id: str,
    ) -> list[types.InlayHint]:
        """Generate inlay hints for all variables/parameters/returns in a scope."""
        hints: list[types.InlayHint] = []
        # Hint columns are code points (Jedi/AST); LSP wants UTF-16, so convert each anchor here.
        hint_lines = source.splitlines()

        # Generate hints for local variables
        annotated_vars = self.get_annotated_variable_names(scope)

        for var_name, type_info in scope.variables.items():
            # Skip if already annotated
            if var_name in annotated_vars:
                continue

            # Skip if type is Unknown or invalid position
            if type_info.type_str == "Unknown":
                continue
            if type_info.line < 0 or type_info.col < 0:
                logger.warning(
                    f"Invalid position for variable {var_name}: "
                    f"line={type_info.line}, col={type_info.col}"
                )
                continue

            # Check if type was validated - show all types, mark invalid ones
            validation_key = f"{scope_id}.var.{var_name}"
            is_valid = self._validity_for(validation_results, validation_key)
            if is_valid is not None:
                hint = self._build_type_hint(
                    type_info.line,
                    self._col_to_utf16(hint_lines, type_info.line, type_info.col + len(var_name)),
                    " ",
                    type_info.type_str,
                    is_valid,
                )
                hints.append(hint)

        # Generate hints for parameters (function scopes only)
        if scope.scope_type == ScopeType.FUNCTION:
            # Get function AST node to check for existing annotations
            func_node = scope.ast_node
            if func_node and isinstance(func_node, ast.FunctionDef | ast.AsyncFunctionDef):
                # Scan all param kinds for annotations; missing one → duplicate hint (issue #9).
                annotated_params = {
                    arg.arg
                    for arg in (
                        *func_node.args.posonlyargs,
                        *func_node.args.args,
                        *func_node.args.kwonlyargs,
                        func_node.args.vararg,
                        func_node.args.kwarg,
                    )
                    if arg is not None and arg.annotation
                }

                in_class = scope.parent is not None and scope.parent.scope_type == ScopeType.CLASS

                for param_name, type_info in scope.parameters.items():
                    # Skip if already annotated
                    if param_name in annotated_params:
                        continue

                    # Skip a method's receiver: insertion declines it, so proposing it would
                    # offer the developer a hint that accepting does nothing with.
                    if is_implicit_receiver(func_node, param_name, in_class=in_class):
                        continue

                    # Skip if type is Unknown or invalid position
                    if type_info.type_str == "Unknown":
                        continue
                    if type_info.line < 0 or type_info.col < 0:
                        logger.warning(
                            f"Invalid position for parameter {param_name}: "
                            f"line={type_info.line}, col={type_info.col}"
                        )
                        continue

                    # Check if type was validated - show all types, mark invalid ones
                    validation_key = f"{scope_id}.param.{param_name}"
                    is_valid = self._validity_for(validation_results, validation_key)
                    if is_valid is not None:
                        hint = self._build_type_hint(
                            type_info.line,
                            self._col_to_utf16(
                                hint_lines, type_info.line, type_info.col + len(param_name)
                            ),
                            ": ",
                            type_info.type_str,
                            is_valid,
                        )
                        hints.append(hint)

                # Generate return type hint
                validation_key = f"{scope_id}.return"
                return_is_valid = self._validity_for(validation_results, validation_key)
                if (
                    scope.return_type
                    and scope.return_type.type_str != "Unknown"
                    and not func_node.returns
                    and return_is_valid is not None
                ):
                    # Anchor after the signature's ')' — which may not be on the def line.
                    signature_end = _signature_end(hint_lines, func_node)
                    if signature_end is not None:
                        close_line, close_col = signature_end
                        hint = self._build_type_hint(
                            close_line,
                            codepoint_to_utf16(hint_lines[close_line], close_col),
                            " -> ",
                            scope.return_type.type_str,
                            return_is_valid,
                        )
                        hints.append(hint)

        return hints

    async def process_usage_hints(
        self,
        source: str,
        file_path: str | None,
        range_start_line: int,
        range_end_line: int,
        inference_result: InferenceResult,
        cancel_token: CancellationToken | None = None,
    ) -> list[types.InlayHint]:
        """Generate async usage-site hints (Phase 4); optional cancel_token threads into Jedi."""
        # PHASE 4: Generate usage-site hints
        start_usage = time.time()
        hints: list[types.InlayHint] = []

        # Collect all name usages in the visible range
        usage_locations = self.name_collector.collect_in_range(
            source,
            range_start_line,
            range_end_line,
            buffer=50,
            include_expressions=False,
        )

        if usage_locations:
            # Get declaration positions to exclude from usage hints
            declaration_positions = self.get_declaration_positions(inference_result.scope_tree)

            # Infer types at usage locations (blocking Jedi call, offloaded)
            locations_to_infer = [(loc.line, loc.col) for loc in usage_locations]
            usage_types = await asyncio.to_thread(
                self.inference_engine.infer_types_at_locations,
                source,
                locations_to_infer,
                file_path,
                cancel_token=cancel_token,
            )

            # Generate usage hints
            usage_hints = self.generate_usage_hints(
                usage_locations,
                usage_types,
                declaration_positions,
                source,
            )
            hints.extend(usage_hints)

            usage_time = time.time() - start_usage
            logger.info(
                f"Phase 4 (Usage Hints): {len(usage_hints)} hints from "
                f"{len(usage_locations)} locations in {usage_time:.3f}s"
            )
        else:
            logger.info("Phase 4 (Usage Hints): No usage locations in range")

        return hints

    def generate_usage_hints(
        self,
        usage_locations: list[NameLocation],
        usage_types: dict[tuple[int, int], str],
        declaration_positions: set[tuple[int, int]],
        source: str | None = None,
    ) -> list[types.InlayHint]:
        """Generate inlay hints for name usage sites, skipping only the declaration sites.

        A read is hinted whether or not its binding carries an annotation, matching parameters,
        which were never suppressed. The type comes from inference at this position rather than
        from matching the name up the scope chain, which is what stops a shadowed local from
        reporting an outer binding's type.
        """
        hints: list[types.InlayHint] = []
        usage_lines = source.splitlines() if source is not None else None

        for loc in usage_locations:
            # Skip declaration sites (they have their own hints)
            if (loc.line, loc.col) in declaration_positions:
                continue

            # Get the type for this location
            type_str = usage_types.get((loc.line, loc.col))
            if not type_str or type_str in ("Unknown", "callable"):
                continue

            # Hint goes after the identifier; NameLocation lines are 1-based (AST), LSP 0-based.
            character = loc.end_col
            if usage_lines is not None:
                character = self._col_to_utf16(usage_lines, loc.line - 1, character)
            hint = types.InlayHint(
                position=types.Position(
                    line=loc.line - 1,  # Convert to 0-based
                    character=character,
                ),
                label=f" {type_str}",
                kind=types.InlayHintKind.Type,
                padding_left=True,
                padding_right=True,
            )
            hints.append(hint)

        return hints

    def get_declaration_positions(self, scope_tree: ScopeTree) -> set[tuple[int, int]]:
        """Get all declaration (line, col) positions (1-based) from a scope tree."""
        positions: set[tuple[int, int]] = set()

        for scope in scope_tree.scopes_by_id.values():
            # Variable declarations
            for type_info in scope.variables.values():
                if type_info.line >= 0 and type_info.col >= 0:
                    # TypeInfo uses 0-based lines, convert to 1-based
                    positions.add((type_info.line + 1, type_info.col))

            # Parameter declarations
            for type_info in scope.parameters.values():
                if type_info.line >= 0 and type_info.col >= 0:
                    positions.add((type_info.line + 1, type_info.col))

        return positions
