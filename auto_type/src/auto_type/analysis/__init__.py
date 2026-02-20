"""Analysis module for scope-aware type inference.

This module provides data structures for analyzing Python code structure:
- Type metadata (TypeInfo, TypeSource)
- Scope representation (Scope, ScopeType, ScopeTree)
- Call graph structures (FunctionNode, CallGraph)
"""

from auto_type.analysis.ast_traversal import (
    extract_loop_variables,
    iter_qualified_function_nodes,
    set_parent_refs,
)
from auto_type.analysis.name_collector import NameCollector, NameLocation
from auto_type.analysis.types import (
    CallGraph,
    FunctionNode,
    Scope,
    ScopeTree,
    ScopeType,
    TypeInfo,
    TypeSource,
)

__all__: list[str] = [
    "CallGraph",
    "FunctionNode",
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
