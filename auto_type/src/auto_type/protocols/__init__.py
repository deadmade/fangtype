"""Protocol definitions for dependency injection interfaces.

This module exports all Protocol classes for backward compatibility.
"""

from auto_type.protocols.diagnostic_engine_protocol import DiagnosticEngineProtocol
from auto_type.protocols.inference_engine_protocol import InferenceEngineProtocol
from auto_type.protocols.type_validator_protocol import TypeValidatorProtocol
from auto_type.protocols.workflow_protocol import TypeAnnotationWorkflowProtocol

__all__ = [
    "DiagnosticEngineProtocol",
    "InferenceEngineProtocol",
    "TypeAnnotationWorkflowProtocol",
    "TypeValidatorProtocol",
]
