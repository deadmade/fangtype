"""Scope-aware type inference: type metadata and scope-representation data structures."""

from fangtype.analysis.ast_traversal import (
    extract_loop_variables,
    iter_qualified_function_nodes,
    set_parent_refs,
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
    "NameCollector",
    "NameLocation",
    "Scope",
    "ScopeTree",
    "ScopeType",
    "TypeInfo",
    "TypeSource",
    "extract_loop_variables",
    "iter_qualified_function_nodes",
    "set_parent_refs",
]
