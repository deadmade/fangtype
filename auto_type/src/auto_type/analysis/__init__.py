"""Analysis module for scope-aware type inference.

This module provides infrastructure for analyzing Python code structure:
- Scope analysis: Building scope trees for modules, functions, classes
- Call graph construction: Tracking function call relationships
- Type propagation: Bottom-up type inference through call graphs
"""

from auto_type.analysis.call_graph_builder import CallGraphBuilder
from auto_type.analysis.scope_analyzer import ScopeAnalyzer
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
    "CallGraphBuilder",
    "FunctionNode",
    "Scope",
    "ScopeAnalyzer",
    "ScopeTree",
    "ScopeType",
    "TypeInfo",
    "TypeSource",
]
