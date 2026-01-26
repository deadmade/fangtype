"""Dependency injection container for the auto_type LSP server.

This module provides a DI container using the 'injector' library.
It manages engine instances and enables easy testing.
"""

import threading
from typing import cast

from injector import Binder, Injector, Module, provider, singleton

from auto_type.analysis.name_collector import NameCollector
from auto_type.diagnostics import DiagnosticEngine
from auto_type.inference import JediInferenceEngine
from auto_type.insertion import UnifiedInsertionEngine
from auto_type.protocols import (
    DiagnosticEngineProtocol,
    InferenceEngineProtocol,
    TypeAnnotationWorkflowProtocol,
    TypeValidatorProtocol,
)
from auto_type.utils.code_action_helper import CodeActionHelper
from auto_type.utils.diagnostic_helper import DiagnosticHelper
from auto_type.utils.inlay_hint_helper import InlayHintHelper
from auto_type.validation import MypyTypeValidator
from auto_type.workflow import TypeAnnotationWorkflow

# Global container instance
_injector: "Injector | None" = None
_lock = threading.Lock()


class AutoTypeModule(Module):
    """Injector module for binding auto_type dependencies."""

    def configure(self, binder: Binder) -> None:
        """Bind concrete implementations as singletons."""
        binder.bind(JediInferenceEngine, scope=singleton)
        binder.bind(MypyTypeValidator, scope=singleton)
        binder.bind(UnifiedInsertionEngine, scope=singleton)
        binder.bind(DiagnosticEngine, scope=singleton)
        binder.bind(CodeActionHelper, scope=singleton)
        binder.bind(DiagnosticHelper, scope=singleton)
        binder.bind(InlayHintHelper, scope=singleton)
        binder.bind(NameCollector, scope=singleton)
        binder.bind(TypeAnnotationWorkflow, scope=singleton)

    @provider
    def provide_inference_protocol(self, engine: JediInferenceEngine) -> InferenceEngineProtocol:
        """Provide InferenceEngineProtocol via JediInferenceEngine singleton."""
        return cast("InferenceEngineProtocol", engine)

    @provider
    def provide_validator_protocol(self, validator: MypyTypeValidator) -> TypeValidatorProtocol:
        """Provide TypeValidatorProtocol via MypyTypeValidator singleton."""
        return cast("TypeValidatorProtocol", validator)

    @provider
    def provide_insertion_engine(self, engine: UnifiedInsertionEngine) -> UnifiedInsertionEngine:
        """Provide UnifiedInsertionEngine singleton."""
        return engine

    @provider
    def provide_diagnostic_protocol(self, engine: DiagnosticEngine) -> DiagnosticEngineProtocol:
        """Provide DiagnosticEngineProtocol via DiagnosticEngine singleton."""
        return cast("DiagnosticEngineProtocol", engine)

    @provider
    def provide_workflow_protocol(
        self, workflow: TypeAnnotationWorkflow
    ) -> TypeAnnotationWorkflowProtocol:
        """Provide TypeAnnotationWorkflowProtocol via TypeAnnotationWorkflow singleton."""
        return cast("TypeAnnotationWorkflowProtocol", workflow)


def get_container() -> Injector:
    """Get the global injector instance.

    Creates a new injector with default configuration if none exists.

    Returns:
        The global Injector instance
    """
    global _injector
    if _injector is None:
        with _lock:
            if _injector is None:
                _injector = Injector([AutoTypeModule()])
    return _injector


def set_container(injector: Injector) -> None:
    """Set the global injector instance.

    This is primarily used for testing to inject a container
    with mock dependencies.

    Args:
        injector: The injector to use as the global instance
    """
    global _injector
    _injector = injector


def reset_container() -> None:
    """Reset the global injector to None.

    Forces a fresh injector to be created on the next get_container() call.
    Useful for test cleanup to ensure test isolation.
    """
    global _injector
    _injector = None
