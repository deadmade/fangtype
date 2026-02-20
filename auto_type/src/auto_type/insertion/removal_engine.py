"""Type annotation removal helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import libcst as cst
from libcst.metadata import PositionProvider


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
    will_remove: list[dict[str, Any]] = field(default_factory=list)
    will_skip: list[dict[str, Any]] = field(default_factory=list)
    requested_targets: set[str] | None = None
    matched_targets: set[str] = field(default_factory=set)

    def record_removal(self, name: str, annotation: cst.Annotation, line: int) -> None:
        self.removed_count += 1
        self.matched_targets.add(name)
        self.will_remove.append(
            {"variable": name, "type": _annotation_to_str(annotation), "line": line}
        )

    def record_skip(self, name: str, reason: str, line: int) -> None:
        self.will_skip.append({"variable": name, "reason": reason, "line": line})

    def mark_matched(self, name: str) -> None:
        self.matched_targets.add(name)

    def finalize(self) -> dict[str, Any]:
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

    def __init__(self, targets: set[str] | None, include_functions: bool) -> None:
        self._targets = targets
        self._include_functions = include_functions
        self._summary = RemovalSummary(requested_targets=targets.copy() if targets else None)

    def _should_process(self, name: str) -> bool:
        return self._targets is None or name in self._targets

    def leave_AnnAssign(
        self, original_node: cst.AnnAssign, updated_node: cst.AnnAssign
    ) -> cst.BaseStatement:
        target_name = _target_name(original_node.target)
        if target_name is None or not self._should_process(target_name):
            return updated_node

        metadata = self.get_metadata(PositionProvider, original_node)
        if original_node.value is None:
            self._summary.record_skip(target_name, "no value", metadata.start.line)
            return updated_node

        equal = original_node.equal
        if isinstance(equal, cst.AssignEqual):
            before = equal.whitespace_before
            after = equal.whitespace_after
        else:
            before = cst.SimpleWhitespace(" ")
            after = cst.SimpleWhitespace(" ")

        assign_target = cst.AssignTarget(
            target=original_node.target,
            whitespace_before_equal=before,
            whitespace_after_equal=after,
        )
        assign = cst.Assign(
            targets=[assign_target], value=original_node.value, semicolon=original_node.semicolon
        )
        self._summary.record_removal(target_name, original_node.annotation, metadata.start.line)
        return assign

    def leave_FunctionDef(
        self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef
    ) -> cst.FunctionDef:
        if not self._include_functions:
            return updated_node

        func_name = original_node.name.value
        if not self._should_process(func_name):
            return updated_node

        metadata = self.get_metadata(PositionProvider, original_node)
        params = updated_node.params

        def _clear_param(param: cst.Param) -> cst.Param:
            annotation = param.annotation
            if annotation is None:
                return param
            self._summary.mark_matched(func_name)
            self._summary.record_removal(
                f"{func_name}.{param.name.value}", annotation, metadata.start.line
            )
            return param.with_changes(annotation=None)

        params = params.with_changes(
            params=[_clear_param(p) for p in params.params],
            posonly_params=[_clear_param(p) for p in params.posonly_params],
            kwonly_params=[_clear_param(p) for p in params.kwonly_params],
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
            self._summary.record_removal(f"{func_name}.return", returns, metadata.start.line)
            returns = None

        return updated_node.with_changes(params=params, returns=returns)

    def summary(self) -> dict[str, Any]:
        return self._summary.finalize()


class TypeRemovalEngine:
    @classmethod
    def _run(
        cls, source: str, variables: list[str] | None, include_functions: bool
    ) -> tuple[cst.Module, _TypeRemovalTransformer]:
        module = cst.parse_module(source)
        transformer = _TypeRemovalTransformer(
            set(variables) if variables else None, include_functions
        )
        wrapper = cst.metadata.MetadataWrapper(module)
        modified = wrapper.visit(transformer)
        return modified, transformer

    @classmethod
    def remove_types(
        cls, source: str, variables: list[str] | None = None, include_functions: bool = False
    ) -> tuple[str, dict[str, Any]]:
        modified, transformer = cls._run(source, variables, include_functions)
        return modified.code, transformer.summary()

    @classmethod
    def preview_removals(cls, source: str, variables: list[str] | None = None) -> dict[str, Any]:
        _, transformer = cls._run(source, variables, include_functions=False)
        summary = transformer.summary()
        summary["total_changes"] = summary["removed_count"]
        return summary
