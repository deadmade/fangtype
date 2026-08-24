"""Scope-aware type inference: type metadata and scope-representation data structures."""

from fangtype.analysis.ast_traversal import (
    SELF_LIKE_NAMES,
    annotated_targets_by_line,
    extract_loop_variables,
    is_implicit_receiver,
    iter_qualified_function_nodes,
    set_parent_refs,
)
from fangtype.analysis.forward_refs import (
    ForwardRefContext,
    build_forward_ref_context,
    quote_annotation,
)
from fangtype.analysis.name_collector import NameCollector, NameLocation
from fangtype.analysis.types import (
    Scope,
    ScopeTree,
    ScopeType,
    TypeInfo,
    TypeSource,
)

__all__: list[str] = [
    "SELF_LIKE_NAMES",
    "ForwardRefContext",
    "NameCollector",
    "NameLocation",
    "Scope",
    "ScopeTree",
    "ScopeType",
    "TypeInfo",
    "TypeSource",
    "annotated_targets_by_line",
    "build_forward_ref_context",
    "extract_loop_variables",
    "is_implicit_receiver",
    "iter_qualified_function_nodes",
    "quote_annotation",
    "set_parent_refs",
]
