"""Type annotation removal engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypedDict

import libcst as cst
from libcst.metadata import PositionProvider


class RemovalRecord(TypedDict):
    variable: str
    type: str
    line: int
    target_kind: str
    function_name: str | None
    parameter_name: str | None


class SkipRecord(TypedDict):
    variable: str
    reason: str
    line: int


def _annotation_to_str(annotation: cst.Annotation) -> str:
    module = cst.Module([cst.SimpleStatementLine([cst.Expr(annotation.annotation)])])
    return module.code.strip()


def _target_name(node: cst.CSTNode) -> str | None:
    if isinstance(node, cst.Name):
        return node.value
    if isinstance(node, cst.Attribute):
        value_name = _target_name(node.value)
        if value_name:
            return f"{value_name}.{node.attr.value}"
    return None


@dataclass
class RemovalSummary:
    removed_count: int = 0
    will_remove: list[RemovalRecord] = field(default_factory=list)
    will_skip: list[SkipRecord] = field(default_factory=list)
    requested_targets: set[str] | None = None
    matched_targets: set[str] = field(default_factory=set)

    def record_removal(
        self,
        name: str,
        annotation: cst.Annotation,
        line: int,
        target_kind: str,
        function_name: str | None = None,
        parameter_name: str | None = None,
    ) -> None:
        self.removed_count += 1
        self.matched_targets.add(name)
        self.will_remove.append(
            {
                "variable": name,
                "type": _annotation_to_str(annotation),
                "line": line,
                "target_kind": target_kind,
                "function_name": function_name,
                "parameter_name": parameter_name,
            }
        )

    def record_skip(self, name: str, reason: str, line: int) -> None:
        # A skipped target was still found; mark it so finalize() doesn't also list it as not_found.
        self.matched_targets.add(name)
        self.will_skip.append({"variable": name, "reason": reason, "line": line})

    def mark_matched(self, name: str) -> None:
        self.matched_targets.add(name)

    def finalize(self) -> dict[str, object]:
        missing = []
        if self.requested_targets is not None:
            missing = sorted(self.requested_targets - self.matched_targets)
        return {
            "success": self.removed_count > 0,
            "removed_count": self.removed_count,
            "will_remove": self.will_remove,
            "will_skip": self.will_skip,
            "not_found": missing,
        }


class _TypeRemovalTransformer(cst.CSTTransformer):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(
        self, targets: set[str] | None, include_functions: bool, line: int | None = None
    ) -> None:
        self._targets = targets
        self._include_functions = include_functions
        # Innermost binding scope, so a bare declaration in a method is told apart from one in
        # a class body. Only the top of the stack matters; a def inside a class re-opens.
        self._scopes: list[str] = []
        self._line = line  # 1-based; None means every line (whole-file removal).
        self._summary = RemovalSummary(requested_targets=targets.copy() if targets else None)

    def _should_process(self, name: str, line: int) -> bool:
        return (self._targets is None or name in self._targets) and (
            self._line is None or self._line == line
        )

    def leave_AnnAssign(
        self, original_node: cst.AnnAssign, updated_node: cst.AnnAssign
    ) -> cst.BaseSmallStatement | cst.RemovalSentinel:
        metadata = self.get_metadata(PositionProvider, original_node)
        target_name = _target_name(original_node.target)
        if target_name is None or not self._should_process(target_name, metadata.start.line):
            return updated_node

        target_kind = "attribute" if isinstance(original_node.target, cst.Attribute) else "variable"
        if original_node.value is None:
            return self._remove_declaration(
                updated_node,
                target_name,
                original_node.annotation,
                metadata.start.line,
                target_kind,
            )

        equal = original_node.equal
        before: cst.SimpleWhitespace = cst.SimpleWhitespace(" ")
        after: cst.SimpleWhitespace = cst.SimpleWhitespace(" ")
        if isinstance(equal, cst.AssignEqual):
            if isinstance(equal.whitespace_before, cst.SimpleWhitespace):
                before = equal.whitespace_before
            if isinstance(equal.whitespace_after, cst.SimpleWhitespace):
                after = equal.whitespace_after

        assign_target = cst.AssignTarget(
            target=original_node.target,
            whitespace_before_equal=before,
            whitespace_after_equal=after,
        )
        assign = cst.Assign(
            targets=[assign_target], value=original_node.value, semicolon=original_node.semicolon
        )
        self._summary.record_removal(
            target_name,
            original_node.annotation,
            metadata.start.line,
            target_kind=target_kind,
        )
        return assign

    def _remove_declaration(
        self,
        updated_node: cst.AnnAssign,
        target_name: str,
        annotation: cst.Annotation,
        line: int,
        target_kind: str,
    ) -> cst.BaseSmallStatement | cst.RemovalSentinel:
        """Delete a value-less ``x: int``, which is the standalone declaration the insertion
        path writes when PEP 526 cannot annotate the binding in place.

        There is no assignment underneath to fall back to, so the inverse of writing the line
        is deleting it. Class scope is the exception -- there a bare declaration MAY be a
        field of a dataclass, TypedDict or NamedTuple, and this method tests the scope alone,
        so it cannot tell. Dropping it would then remove a member rather than a type claim,
        which is more than a removal request asks for.
        """
        if self._scopes and self._scopes[-1] == "class":
            self._summary.record_skip(target_name, "class-level declaration", line)
            return updated_node

        self._summary.record_removal(target_name, annotation, line, target_kind=target_kind)
        return cst.RemoveFromParent()

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        self._scopes.append("class")

    def leave_ClassDef(
        self, original_node: cst.ClassDef, updated_node: cst.ClassDef
    ) -> cst.ClassDef:
        self._scopes.pop()
        return updated_node

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        self._scopes.append("function")

    def leave_FunctionDef(
        self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef
    ) -> cst.FunctionDef:
        self._scopes.pop()
        if not self._include_functions:
            return updated_node

        metadata = self.get_metadata(PositionProvider, original_node)
        func_name = original_node.name.value
        if not self._should_process(func_name, metadata.start.line):
            return updated_node

        params = updated_node.params

        def _clear_param(param: cst.Param) -> cst.Param:
            annotation = param.annotation
            if annotation is None:
                return param
            self._summary.mark_matched(func_name)
            self._summary.record_removal(
                f"{func_name}.{param.name.value}",
                annotation,
                metadata.start.line,
                target_kind="function_param",
                function_name=func_name,
                parameter_name=param.name.value,
            )
            return param.with_changes(annotation=None)

        new_params: list[cst.Param] = [_clear_param(p) for p in params.params]
        new_posonly_params: list[cst.Param] = [_clear_param(p) for p in params.posonly_params]
        new_kwonly_params: list[cst.Param] = [_clear_param(p) for p in params.kwonly_params]
        params = params.with_changes(
            params=new_params,
            posonly_params=new_posonly_params,
            kwonly_params=new_kwonly_params,
            star_arg=_clear_param(params.star_arg)
            if isinstance(params.star_arg, cst.Param)
            else params.star_arg,
            star_kwarg=_clear_param(params.star_kwarg)
            if isinstance(params.star_kwarg, cst.Param)
            else params.star_kwarg,
        )

        returns = updated_node.returns
        if returns is not None:
            self._summary.mark_matched(func_name)
            self._summary.record_removal(
                f"{func_name}.return",
                returns,
                metadata.start.line,
                target_kind="function_return",
                function_name=func_name,
            )
            returns = None

        return updated_node.with_changes(params=params, returns=returns)

    def summary(self) -> dict[str, object]:
        return self._summary.finalize()


class RemovalEngine:
    """Strips type annotations via one LibCST pass; DI singleton injected into the workflow."""

    @staticmethod
    def _run(
        source: str,
        variables: list[str] | None,
        include_functions: bool,
        line: int | None = None,
    ) -> tuple[cst.Module, _TypeRemovalTransformer]:
        module = cst.parse_module(source)
        # `is not None`, not truthiness: an empty list means "remove nothing", not "remove all".
        transformer = _TypeRemovalTransformer(
            set(variables) if variables is not None else None, include_functions, line
        )
        wrapper = cst.metadata.MetadataWrapper(module)
        modified = wrapper.visit(transformer)
        return modified, transformer

    def remove_types(
        self,
        source: str,
        variables: list[str] | None = None,
        include_functions: bool = False,
        line: int | None = None,
    ) -> tuple[str, dict[str, object]]:
        modified, transformer = self._run(source, variables, include_functions, line)
        return modified.code, transformer.summary()

    def preview_removals(
        self,
        source: str,
        variables: list[str] | None = None,
        include_functions: bool = False,
    ) -> dict[str, object]:
        _, transformer = self._run(source, variables, include_functions)
        summary = transformer.summary()
        summary["total_changes"] = summary["removed_count"]
        return summary
