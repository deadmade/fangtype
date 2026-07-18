"""DI container wiring concrete impls behind Protocols via injector; no global container."""

from typing import cast

from injector import Binder, Injector, Module, provider, singleton

from fangtype.analysis import NameCollector
from fangtype.diagnostics import DiagnosticEngine
from fangtype.inference import JediInferenceEngine
from fangtype.insertion import InsertionEngine
from fangtype.protocols import (
    DiagnosticEngineProtocol,
    InferenceEngineProtocol,
    TypeValidatorProtocol,
)
from fangtype.removal import RemovalEngine
from fangtype.utils.code_action_helper import CodeActionHelper
from fangtype.utils.document_cache import DocumentCache
from fangtype.utils.inlay_hint_helper import InlayHintHelper
from fangtype.utils.settings import Settings
from fangtype.validation import MypyTypeValidator
from fangtype.workflow import TypeAnnotationWorkflow


class FangtypeModule(Module):
    """Injector module for binding fangtype dependencies."""

    def __init__(self, inference_engine_cls: type = JediInferenceEngine) -> None:
        """Bind the given inference engine class behind InferenceEngineProtocol."""
        self._inference_engine_cls = inference_engine_cls

    def configure(self, binder: Binder) -> None:
        """Bind concrete implementations as singletons."""
        binder.bind(Settings, scope=singleton)
        binder.bind(DocumentCache, scope=singleton)
        binder.bind(self._inference_engine_cls, scope=singleton)
        binder.bind(MypyTypeValidator, scope=singleton)
        binder.bind(InsertionEngine, scope=singleton)
        binder.bind(RemovalEngine, scope=singleton)
        binder.bind(DiagnosticEngine, scope=singleton)
        binder.bind(CodeActionHelper, scope=singleton)
        binder.bind(InlayHintHelper, scope=singleton)
        binder.bind(NameCollector, scope=singleton)
        binder.bind(TypeAnnotationWorkflow, scope=singleton)

    # injector's @provider is Any-leaking third-party; no annotation satisfies disallow_any_expr.
    @provider  # type: ignore[misc]
    def provide_inference_protocol(self, injector: Injector) -> InferenceEngineProtocol:
        """Provide InferenceEngineProtocol via the configured engine singleton."""
        return cast("InferenceEngineProtocol", injector.get(self._inference_engine_cls))

    @provider  # type: ignore[misc]
    def provide_validator_protocol(self, validator: MypyTypeValidator) -> TypeValidatorProtocol:
        """Provide TypeValidatorProtocol via MypyTypeValidator singleton."""
        return cast("TypeValidatorProtocol", validator)

    @provider  # type: ignore[misc]
    def provide_diagnostic_protocol(self, engine: DiagnosticEngine) -> DiagnosticEngineProtocol:
        """Provide DiagnosticEngineProtocol via DiagnosticEngine singleton."""
        return cast("DiagnosticEngineProtocol", engine)


INFERENCE_ENGINES: dict[str, type] = {
    "jedi": JediInferenceEngine,
}


def resolve_engine_name(name: str | None) -> str:
    """Resolve an inference-engine name to a valid INFERENCE_ENGINES key, falling back to jedi."""
    if name in INFERENCE_ENGINES:
        return name
    return "jedi"


def build_container(engine: str = "jedi") -> Injector:
    """Build a fresh Injector wired to the named inference engine (not installed as global)."""
    return Injector([FangtypeModule(INFERENCE_ENGINES[engine])])
