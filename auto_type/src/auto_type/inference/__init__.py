"""Type inference module for auto-type."""

from auto_type.inference.contextual_inference import ContextualInferenceEngine
from auto_type.inference.type_propagation import TypePropagationEngine
from auto_type.inference.unified_inference import InferenceResult, UnifiedInferenceEngine

__all__: list[str] = [
    "ContextualInferenceEngine",
    "InferenceResult",
    "TypePropagationEngine",
    "UnifiedInferenceEngine",
]
