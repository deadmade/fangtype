"""Analysis module for scope-aware type inference.

This module provides data structures for analyzing Python code structure:
- Type metadata (TypeInfo, TypeSource)
- Scope representation (Scope, ScopeType, ScopeTree)
- Call graph structures (FunctionNode, CallGraph)
"""

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
    "Scope",
    "ScopeTree",
    "ScopeType",
    "TypeInfo",
    "TypeSource",
]
