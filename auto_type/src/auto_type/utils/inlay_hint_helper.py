import ast
import logging
import time
from typing import Any

from injector import inject
from lsprotocol import types

from auto_type.analysis.name_collector import NameCollector, NameLocation
from auto_type.analysis.types import ScopeType
from auto_type.protocols import (
    InferenceEngineProtocol,
)

logger = logging.getLogger(__name__)


class InlayHintHelper:
    """Helper class for generating inlay hints.

    Some methods are async because they use the async inference engine.
    """

    @inject
    def __init__(
        self, name_collector: NameCollector, inference_engine: InferenceEngineProtocol
    ) -> None:
        self.name_collector = name_collector
        self.inference_engine = inference_engine

    def get_annotated_variable_names(self, scope: Any) -> set[str]:
        """Get names of variables with explicit type annotations in a scope.

        Detects variables declared with type annotations (e.g., `x: int = 4`)
        by finding ast.AnnAssign nodes, which represent annotated assignments.

        Args:
            scope: Scope object containing ast_node

        Returns:
            Set of variable names that already have type annotations
        """
        annotated_vars: set[str] = set()
        ast_node = scope.ast_node

        if ast_node is None:
            return annotated_vars

        # Walk all nodes within this scope's AST node
        for node in ast.walk(ast_node):
            # Skip nested function/class definitions - they have their own scopes
            if node is not ast_node and isinstance(
                node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
            ):
                continue

            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                annotated_vars.add(node.target.id)

        return annotated_vars

    def generate_hints_for_scope(
        self, scope: Any, source: str, validated_types: dict[str, str], scope_id: str
    ) -> list[types.InlayHint]:
        """Generate inlay hints for all variables/parameters/returns in a scope.

        Uses the scope tree directly - no manual AST walking needed!

        Args:
            scope: Scope object containing variables, parameters, and return type
            source: Source code (needed for return type hint positioning)
            validated_types: Pre-validated types dict with keys like "scope_id.category.name"
            scope_id: ID of this scope for constructing validated_types keys

        Returns:
            List of inlay hints for this scope
        """
        hints: list[types.InlayHint] = []

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

            # Check if type was validated
            validation_key = f"{scope_id}.var.{var_name}"
            if validation_key in validated_types:
                hint = types.InlayHint(
                    position=types.Position(
                        line=type_info.line, character=type_info.col + len(var_name)
                    ),
                    label=f" {type_info.type_str}",
                    kind=types.InlayHintKind.Type,
                    padding_left=False,
                    padding_right=False,
                )
                hints.append(hint)

        # Generate hints for parameters (function scopes only)
        if scope.scope_type == ScopeType.FUNCTION:
            # Get function AST node to check for existing annotations
            func_node = scope.ast_node
            if func_node and isinstance(func_node, ast.FunctionDef | ast.AsyncFunctionDef):
                # Build map of parameter names to annotations
                annotated_params = {arg.arg for arg in func_node.args.args if arg.annotation}

                for param_name, type_info in scope.parameters.items():
                    # Skip if already annotated
                    if param_name in annotated_params:
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

                    # Check if type was validated
                    validation_key = f"{scope_id}.param.{param_name}"
                    if validation_key in validated_types:
                        hint = types.InlayHint(
                            position=types.Position(
                                line=type_info.line, character=type_info.col + len(param_name)
                            ),
                            label=f": {type_info.type_str}",
                            kind=types.InlayHintKind.Type,
                            padding_left=False,
                            padding_right=False,
                        )
                        hints.append(hint)

                # Generate return type hint
                validation_key = f"{scope_id}.return"
                if (
                    scope.return_type
                    and scope.return_type.type_str != "Unknown"
                    and not func_node.returns
                    and validation_key in validated_types
                ):
                    # Find closing paren position
                    func_line = func_node.lineno - 1
                    lines = source.splitlines()
                    if func_line < len(lines):
                        line_text = lines[func_line]
                        # Find closing paren
                        close_paren_pos = line_text.rfind(")")
                        if close_paren_pos != -1:
                            hint = types.InlayHint(
                                position=types.Position(
                                    line=func_line, character=close_paren_pos + 1
                                ),
                                label=f" -> {scope.return_type.type_str}",
                                kind=types.InlayHintKind.Type,
                                padding_left=False,
                                padding_right=False,
                            )
                            hints.append(hint)

        return hints

    async def process_usage_hints(
        self,
        source: str,
        file_path: str | None,
        range_start_line: int,
        range_end_line: int,
        inference_result: Any,
    ) -> list[types.InlayHint]:
        """Generate usage-site hints (Phase 4).

        This method is async because it uses the async inference engine.

        Args:
            source: Source code of the document
            file_path: Path to the file
            range_start_line: Start line of the visible range
            range_end_line: End line of the visible range
            inference_result: InferenceResult containing scope_tree

        Returns:
            List of generated inlay hints
        """
        # PHASE 4: Generate usage-site hints
        start_usage = time.time()
        hints: list[types.InlayHint] = []

        # Collect all name usages in the visible range
        usage_locations = self.name_collector.collect_in_range(
            source,
            range_start_line,
            range_end_line,
            buffer=50,
        )

        if usage_locations:
            # Get declaration positions to exclude from usage hints
            declaration_positions = self.get_declaration_positions(inference_result.scope_tree)

            # Infer types at usage locations (async)
            locations_to_infer = [(loc.line, loc.col) for loc in usage_locations]
            usage_types = await self.inference_engine.infer_types_at_locations(
                source, locations_to_infer, file_path
            )

            # Generate usage hints
            usage_hints = self.generate_usage_hints(
                usage_locations, usage_types, declaration_positions
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
    ) -> list[types.InlayHint]:
        """Generate inlay hints for name usage sites.

        Creates InlayHint objects for each location where a variable is used
        (as opposed to defined). This allows showing type information throughout
        the code, not just at declaration sites.

        Args:
            usage_locations: List of NameLocation objects for usage sites
            usage_types: Dict mapping (line, col) to inferred type string
            declaration_positions: Set of (line, col) for declarations to skip

        Returns:
            List of InlayHint objects for usage sites
        """
        hints: list[types.InlayHint] = []

        for loc in usage_locations:
            # Skip declaration sites (they have their own hints)
            if (loc.line, loc.col) in declaration_positions:
                continue

            # Get the type for this location
            type_str = usage_types.get((loc.line, loc.col))
            if not type_str or type_str in ("Unknown", "callable"):
                continue

            # Create hint positioned after the identifier
            # Line in LSP is 0-based, but NameLocation uses 1-based (AST convention)
            hint = types.InlayHint(
                position=types.Position(
                    line=loc.line - 1,  # Convert to 0-based
                    character=loc.end_col,
                ),
                label=f" {type_str}",
                kind=types.InlayHintKind.Type,
                padding_left=True,
                padding_right=True,
            )
            hints.append(hint)

        return hints

    def get_declaration_positions(self, scope_tree: Any) -> set[tuple[int, int]]:
        """Get all declaration positions from a scope tree.

        Used to exclude declaration positions when generating usage hints,
        since declarations already have their own hints.

        Args:
            scope_tree: ScopeTree object containing all scopes

        Returns:
            Set of (line, col) tuples for all variable/parameter declarations
            (using 1-based line numbers to match NameLocation)
        """
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
