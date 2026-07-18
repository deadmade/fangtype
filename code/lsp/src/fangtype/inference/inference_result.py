"""Inference result data structures — the InferenceResult class holding type inference results."""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, TypedDict

from fangtype.utils.position_encoding import ast_source_lines

if TYPE_CHECKING:
    from fangtype.analysis import Scope, ScopeTree, TypeInfo


class FunctionInsertionInfo(TypedDict):
    """Structured function insertion payload."""

    name: str
    params: dict[str, str]
    return_type: str | None


class InferenceResult:
    """Result of type inference: a scope_tree of scopes/types plus the original source."""

    def __init__(
        self,
        scope_tree: ScopeTree,
        source: str,
        *,
        is_complete: bool = True,
    ) -> None:
        """Init; is_complete=False marks a never-cache degraded fallback (recomputed later)."""
        self.scope_tree = scope_tree
        self.source = source
        self.is_complete = is_complete
        # Split like the tokenizer (\n/\r/\r\n only) so indices match TypeInfo.line (ast lineno).
        self._source_lines = ast_source_lines(source)

    def _has_inline_annotation(self, name: str, line_0: int) -> bool:
        """Check if ``name`` is already inline-annotated at ``line_0``."""
        if line_0 < 0 or line_0 >= len(self._source_lines):
            return False

        line_content = self._source_lines[line_0]
        comment_start = line_content.find("#")
        if comment_start != -1:
            line_content = line_content[:comment_start]
        line_content = line_content.strip()

        patterns = [f"{name}:", f"{name} :"]
        return any(
            line_content.startswith(pattern) or f" {pattern}" in line_content
            for pattern in patterns
        )

    def get_variable_insertions(self, *, per_binding: bool = False) -> dict[tuple[int, str], str]:
        """Unannotated vars: (0-based line, name)→type; per_binding=True=every site else last."""
        variable_insertions: dict[tuple[int, str], str] = {}

        # Process all scopes for variables
        for scope in self.scope_tree.scopes_by_id.values():
            if per_binding:
                bindings = [
                    (name, ti) for name, history in scope.variable_history.items() for ti in history
                ]
            else:
                bindings = list(scope.variables.items())

            for var_name, type_info in bindings:
                if not self._binding_is_insertable(scope, var_name, type_info):
                    continue
                # Use the specific line where this variable is assigned (already 0-based).
                variable_insertions[(type_info.line, var_name)] = type_info.type_str

        return variable_insertions

    def _binding_is_insertable(self, scope: Scope, var_name: str, type_info: TypeInfo) -> bool:
        """Insert filter: rejects Unknown, global/nonlocal, comprehension, inline-annotated."""
        if type_info.type_str == "Unknown":
            return False
        if var_name in scope.nonlocal_or_global_names:
            return False
        if (type_info.line, type_info.col, var_name) in scope.comprehension_target_positions:
            return False
        return not self._has_inline_annotation(var_name, type_info.line)

    def get_variable_insertion_candidates(self) -> dict[tuple[str, str], list[tuple[int, str]]]:
        """{(scope_id,name):[(line0,type_str)]} newest-first; newest valid binding not last."""
        candidates: dict[tuple[str, str], list[tuple[int, str]]] = {}
        for scope in self.scope_tree.scopes_by_id.values():
            for var_name, history in scope.variable_history.items():
                for type_info in reversed(history):
                    if not self._binding_is_insertable(scope, var_name, type_info):
                        continue
                    candidates.setdefault((scope.scope_id, var_name), []).append(
                        (type_info.line, type_info.type_str)
                    )
        return candidates

    def get_function_insertions(self) -> dict[tuple[int, str], FunctionInsertionInfo]:
        """Functions missing param/return annots keyed (line0, name)→FunctionInsertionInfo."""
        function_insertions: dict[tuple[int, str], FunctionInsertionInfo] = {}

        # Helper to check if function already has complete annotations
        def has_complete_annotations(scope: Scope) -> tuple[dict[str, str], str | None]:
            """Check which annotations are missing for a function."""
            missing_params = {}
            missing_return = None

            # Check parameters
            for param_name, type_info in scope.parameters.items():
                if type_info.type_str != "Unknown" and not self._param_has_annotation(
                    scope.ast_node, param_name
                ):
                    missing_params[param_name] = type_info.type_str

            # Check return type
            if (
                scope.return_type
                and scope.return_type.type_str != "Unknown"
                and not self._function_has_return_annotation(scope.ast_node)
            ):
                missing_return = scope.return_type.type_str

            return missing_params, missing_return

        # Process all function scopes
        for scope in self.scope_tree.get_all_function_scopes():
            missing_params, missing_return = has_complete_annotations(scope)

            # Skip if function doesn't need any annotations
            if not missing_params and missing_return is None:
                continue

            # Extract function name from scope_id
            func_name = self._extract_function_name(scope.scope_id)

            # Get function definition line (0-based)
            line_0_based = 0  # Default fallback
            if isinstance(scope.ast_node, ast.FunctionDef | ast.AsyncFunctionDef):
                line_0_based = scope.ast_node.lineno - 1

            # Create function insertion info
            key = (line_0_based, func_name)
            function_insertions[key] = {
                "name": func_name,
                "params": missing_params,
                "return_type": missing_return,
            }

        return function_insertions

    def get_attribute_insertions(self) -> dict[tuple[int, str], str]:
        """Unannotated attrs (1-based line, name)→type; dotted for non-self, bare for self."""
        attribute_insertions: dict[tuple[int, str], str] = {}

        # Process all scopes for attributes
        for scope in self.scope_tree.scopes_by_id.values():
            for attr_name, type_info in scope.attributes.items():
                # Skip if type is unknown or already has annotation
                if type_info.type_str == "Unknown":
                    continue

                # Convert to 1-based: workflow.py's insertion path expects 1-based line numbers.
                line_1_based = type_info.line + 1

                # Rebuild dotted self-attr name for inline check; inlined to dodge an import cycle.
                source_name = attr_name if "." in attr_name else f"self.{attr_name}"
                if self._has_inline_annotation(source_name, type_info.line):
                    continue

                # Use the specific line where this attribute is assigned
                key = (line_1_based, attr_name)
                attribute_insertions[key] = type_info.type_str

        return attribute_insertions

    def _param_has_annotation(self, func_node: ast.AST, param_name: str) -> bool:
        """True if param annotated; scans all buckets (posonly/plain/kwonly/vararg/kwarg)."""
        if not isinstance(func_node, ast.FunctionDef | ast.AsyncFunctionDef):
            return False

        all_args = [
            *func_node.args.posonlyargs,
            *func_node.args.args,
            *func_node.args.kwonlyargs,
        ]
        if func_node.args.vararg is not None:
            all_args.append(func_node.args.vararg)
        if func_node.args.kwarg is not None:
            all_args.append(func_node.args.kwarg)

        for arg in all_args:
            if arg.arg == param_name:
                return arg.annotation is not None
        return False

    def _function_has_return_annotation(self, func_node: ast.AST) -> bool:
        """Check if a function already has a return type annotation."""
        if not isinstance(func_node, ast.FunctionDef | ast.AsyncFunctionDef):
            return False
        return func_node.returns is not None

    def _extract_function_name(self, scope_id: str) -> str:
        """Extract clean function name from scope ID."""
        # Format: "func:name@12" or "func:name#1" or "class:Class@3.method@4"
        if ":" not in scope_id:
            return scope_id

        name_part = scope_id.split(":", 1)[1]
        # Remove lambda counter suffix if present
        if "#" in name_part:
            name_part = name_part.split("#")[0]
        # For class methods, take the method name
        if "." in name_part:
            name_part = name_part.split(".")[-1]
        # Drop the def-line discriminator that keeps same-named siblings apart.
        if "@" in name_part:
            name_part = name_part.rsplit("@", 1)[0]

        return name_part
