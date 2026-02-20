"""Type inference module for auto-type.

This module provides type inference capabilities using Jedi.
"""

from auto_type.inference.inference_result import InferenceResult
from auto_type.inference.jedi_engine import JediInferenceEngine
from auto_type.inference.jedi_project import find_project_root
from auto_type.inference.jedi_scope_builder import build_scope_tree
from auto_type.inference.jedi_type_formatter import format_types
from auto_type.inference.types import TypeInferenceContext, TypeInfo

__all__: list[str] = [
    "InferenceResult",
    "JediInferenceEngine",
    "TypeInferenceContext",
    "TypeInfo",
    "build_scope_tree",
    "find_project_root",
    "format_types",
]
