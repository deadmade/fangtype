"""DI Protocol interface re-exports (non-exhaustive; e.g. TypeProbe imports directly)."""

from fangtype.protocols.diagnostic_engine_protocol import DiagnosticEngineProtocol
from fangtype.protocols.inference_engine_protocol import InferenceEngineProtocol
from fangtype.protocols.type_validator_protocol import TypeValidatorProtocol

__all__ = [
    "DiagnosticEngineProtocol",
    "InferenceEngineProtocol",
    "TypeValidatorProtocol",
]
