"""Type inference module for fangtype, providing Jedi-based type inference."""

from fangtype.analysis.types import TypeInfo
from fangtype.inference.inference_result import InferenceResult
from fangtype.inference.jedi.engine import JediInferenceEngine
from fangtype.inference.jedi.project import find_project_root
from fangtype.inference.jedi.scope_builder import build_scope_tree
from fangtype.inference.jedi.type_formatter import format_types

__all__: list[str] = [
    "InferenceResult",
    "JediInferenceEngine",
    "TypeInfo",
    "build_scope_tree",
    "find_project_root",
    "format_types",
]
