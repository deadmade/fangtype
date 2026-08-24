"""Inference result data structures — the InferenceResult class holding type inference results."""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, TypedDict

from fangtype.analysis import ScopeType, annotated_targets_by_line, is_implicit_receiver
from fangtype.inference.type_utils import import_for_annotation

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fangtype.analysis import Scope, ScopeTree, TypeInfo
    from fangtype.analysis.types import ImportHint


def _hint_for(type_info: TypeInfo) -> ImportHint | None:
    """The import an annotation needs, recomputing a synthesised one the writer may have lost.

    A parameter's or a return's TypeInfo is rebuilt after the main walk by the override,
    contract-propagation and call-flow passes, none of which carry the hint forward. A
    synthesised name's import is a pure function of the annotation text, so it is recoverable
    rather than lost. Only a Jedi-resolved concrete class has to survive as data.
    """
    return type_info.import_hint or import_for_annotation(type_info.type_str)


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
        # Built on first use, from the module tree rather than the source text.
        self._annotated_lines: dict[int, set[str]] | None = None

    def _annotated_by_line(self) -> dict[int, set[str]]:
        """Line-keyed PEP 526 annotation index for the module, built once per result."""
        if self._annotated_lines is None:
            self._annotated_lines = annotated_targets_by_line(self.scope_tree.root.ast_node)
        return self._annotated_lines

    def _has_inline_annotation(self, name: str, line_0: int) -> bool:
        """Check if ``name`` is already inline-annotated at ``line_0``.

        Reads the parsed tree rather than the raw line. A substring test cannot tell an
        annotation from a colon that belongs to something else on the same line, so
        ``x = lambda x: x + 1`` used to read as an annotated ``x`` and suppressed itself.
        """
        return name in self._annotated_by_line().get(line_0, set())

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

    def get_import_hints(self) -> dict[tuple[int, str], ImportHint]:
        """(line0, name) -> import needed, for insertable variable bindings that have one.

        Keyed like get_variable_insertions so the insert path can look hints up by the
        same (line, name) key. Latest binding per name wins (matches `scope.variables`).
        """
        hints: dict[tuple[int, str], ImportHint] = {}
        for scope in self.scope_tree.scopes_by_id.values():
            for var_name, type_info in scope.variables.items():
                if not self._binding_is_insertable(scope, var_name, type_info):
                    continue
                if type_info.import_hint is not None:
                    hints[(type_info.line, var_name)] = type_info.import_hint
        return hints

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

    def _missing_function_annotations(
        self, scope: Scope
    ) -> tuple[dict[str, TypeInfo], TypeInfo | None]:
        """Which of a function's params and its return still need an annotation, as TypeInfo.

        Returns the TypeInfo rather than its type_str so callers that need the import hint
        can reach it. get_function_insertions narrows to the string it needs.
        """
        missing_params: dict[str, TypeInfo] = {}
        missing_return: TypeInfo | None = None

        # Check parameters. A method's receiver is skipped: a checker already knows what
        # it refers to, so the annotation costs a reader a line and buys nothing.
        in_class = scope.parent is not None and scope.parent.scope_type == ScopeType.CLASS
        for param_name, type_info in scope.parameters.items():
            if is_implicit_receiver(scope.ast_node, param_name, in_class=in_class):
                continue
            if type_info.type_str != "Unknown" and not self._param_has_annotation(
                scope.ast_node, param_name
            ):
                missing_params[param_name] = type_info

        if (
            scope.return_type
            and scope.return_type.type_str != "Unknown"
            and not self._function_has_return_annotation(scope.ast_node)
        ):
            missing_return = scope.return_type

        return missing_params, missing_return

    def _function_annotation_candidates(
        self,
    ) -> Iterator[tuple[tuple[int, str], dict[str, TypeInfo], TypeInfo | None]]:
        """(line0, name) → the params and return needing annotation, for each such function.

        The single walk both get_function_insertions and get_function_import_hints build on,
        so a hint can never be keyed to a function or a parameter the insertions do not carry.
        """
        for scope in self.scope_tree.get_all_function_scopes():
            missing_params, missing_return = self._missing_function_annotations(scope)
            if not missing_params and missing_return is None:
                continue

            func_name = self._extract_function_name(scope.scope_id)
            line_0_based = 0  # Default fallback
            if isinstance(scope.ast_node, ast.FunctionDef | ast.AsyncFunctionDef):
                line_0_based = scope.ast_node.lineno - 1

            yield (line_0_based, func_name), missing_params, missing_return

    def get_function_insertions(self) -> dict[tuple[int, str], FunctionInsertionInfo]:
        """Functions missing param/return annots keyed (line0, name)→FunctionInsertionInfo."""
        function_insertions: dict[tuple[int, str], FunctionInsertionInfo] = {}

        for key, missing_params, missing_return in self._function_annotation_candidates():
            function_insertions[key] = {
                "name": key[1],
                "params": {name: ti.type_str for name, ti in missing_params.items()},
                "return_type": None if missing_return is None else missing_return.type_str,
            }

        return function_insertions

    def get_function_import_hints(self) -> dict[tuple[int, str, str], ImportHint]:
        """(line0, func_name, param_name) -> import needed, with "return" as the return slot.

        Keyed exactly like the flattened map _validate_function_insertions builds, so the
        candidate-selection probe and the insertion targets can both look a hint up without
        an adapter. "return" cannot collide with a parameter, because it is a keyword.
        """
        hints: dict[tuple[int, str, str], ImportHint] = {}
        for (
            line,
            func_name,
        ), missing_params, missing_return in self._function_annotation_candidates():
            for param_name, type_info in missing_params.items():
                hint = _hint_for(type_info)
                if hint is not None:
                    hints[(line, func_name, param_name)] = hint
            if missing_return is not None:
                hint = _hint_for(missing_return)
                if hint is not None:
                    hints[(line, func_name, "return")] = hint
        return hints

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
