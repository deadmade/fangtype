"""Tests for LSP handler behavior in server.py."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from lsprotocol import types

from auto_type.container import reset_container, set_container
from auto_type.protocols import DiagnosticEngineProtocol, TypeAnnotationWorkflowProtocol
from auto_type.server import (
    did_change,
    did_change_configuration,
    did_open,
    did_save,
    initialized,
    inlay_hints,
    insert_type,
    insert_types_in_file,
    preview_inserts,
    preview_removals,
    remove_types_in_file,
)
from auto_type.server import (
    server as lsp_server,
)
from auto_type.utils import InlayHintHelper, Settings


@dataclass
class FakeDocument:
    uri: str
    source: str


class FakeWorkspace:
    def __init__(self, docs: dict[str, FakeDocument]) -> None:
        self._docs = docs

    def get_text_document(self, uri: str) -> FakeDocument:
        return self._docs[uri]


class FakeContainer:
    def __init__(self) -> None:
        self._registry: dict[object, object] = {}

    def register(self, key: object, value: object) -> None:
        self._registry[key] = value

    def get(self, key: object) -> object:
        return self._registry[key]


class FakeLanguageServer:
    def __init__(self, workspace: FakeWorkspace | None = None, config: list[dict] | None = None):
        self.workspace = workspace
        self._config = config

    async def workspace_configuration_async(self, params: types.ConfigurationParams):
        return self._config


def _make_doc(uri: str, source: str) -> FakeDocument:
    return FakeDocument(uri=uri, source=source)


@pytest.fixture
def fake_container() -> FakeContainer:
    container = FakeContainer()
    set_container(container)
    yield container
    reset_container()


@pytest.fixture
def fake_workspace(monkeypatch: pytest.MonkeyPatch) -> FakeWorkspace:
    uri = "file:///test.py"
    docs = {uri: _make_doc(uri, "x = 1\n")}
    workspace = FakeWorkspace(docs)
    monkeypatch.setattr(lsp_server.protocol, "_workspace", workspace)
    return workspace


def _install_fake_jedi(monkeypatch: pytest.MonkeyPatch, goto_result, infer_result) -> None:
    class FakeScript:
        def __init__(self, source: str, path: str | None = None) -> None:
            self.source = source
            self.path = path

        def goto(self, line: int, column: int):
            return goto_result

        def infer(self, line: int, column: int):
            return infer_result

    fake_jedi = SimpleNamespace(Script=FakeScript)
    monkeypatch.setitem(sys.modules, "jedi", fake_jedi)


async def test_initialized_refreshes_settings(fake_container: FakeContainer) -> None:
    settings = Settings()
    fake_container.register(Settings, settings)

    ls = FakeLanguageServer(config=[{"autoType": {"inlayHintsEnabled": False}}])

    await initialized(ls, types.InitializedParams())

    assert settings.inlay_hints_enabled is False


async def test_did_change_configuration_updates_settings(fake_container: FakeContainer) -> None:
    settings = Settings()
    fake_container.register(Settings, settings)

    params = types.DidChangeConfigurationParams(settings={"autoType": {"mypyEnabled": False}})

    await did_change_configuration(FakeLanguageServer(), params)

    assert settings.mypy_enabled is False


async def test_did_change_configuration_refetches_on_empty(
    fake_container: FakeContainer,
) -> None:
    settings = Settings()
    fake_container.register(Settings, settings)

    ls = FakeLanguageServer(config=[{"autoType": {"preferModernTypes": False}}])
    params = types.DidChangeConfigurationParams(settings={})

    await did_change_configuration(ls, params)

    assert settings.prefer_modern_types is False


async def test_inlay_hints_disabled_returns_empty(
    fake_container: FakeContainer, fake_workspace: FakeWorkspace
) -> None:
    settings = Settings(inlay_hints_enabled=False)
    workflow = MagicMock()
    workflow.collect_and_validate_types = AsyncMock()
    helper = MagicMock(spec=InlayHintHelper)

    fake_container.register(Settings, settings)
    fake_container.register(TypeAnnotationWorkflowProtocol, workflow)
    fake_container.register(InlayHintHelper, helper)

    params = types.InlayHintParams(
        text_document=types.TextDocumentIdentifier(uri="file:///test.py"),
        range=types.Range(start=types.Position(line=0, character=0), end=types.Position(0, 1)),
    )

    result = await inlay_hints(params)

    assert result == []
    workflow.collect_and_validate_types.assert_not_called()


async def test_inlay_hints_collects_and_returns_hints(
    fake_container: FakeContainer, fake_workspace: FakeWorkspace
) -> None:
    settings = Settings(inlay_hints_enabled=True)

    class FakeScopeTree:
        def __init__(self) -> None:
            self.scopes_by_id = {"root": object()}

    fake_inference_result = SimpleNamespace(scope_tree=FakeScopeTree())
    validation_results = {"x": MagicMock()}

    workflow = MagicMock()
    workflow.collect_and_validate_types = AsyncMock(
        return_value=(fake_inference_result, validation_results)
    )

    hint = types.InlayHint(
        position=types.Position(line=0, character=0),
        label=": int",
    )

    helper = MagicMock(spec=InlayHintHelper)
    helper.generate_hints_for_scope.return_value = [hint]
    helper.process_usage_hints = AsyncMock(return_value=[hint])

    fake_container.register(Settings, settings)
    fake_container.register(TypeAnnotationWorkflowProtocol, workflow)
    fake_container.register(InlayHintHelper, helper)

    params = types.InlayHintParams(
        text_document=types.TextDocumentIdentifier(uri="file:///test.py"),
        range=types.Range(start=types.Position(line=0, character=0), end=types.Position(0, 1)),
    )

    result = await inlay_hints(params)

    assert len(result) == 2
    helper.generate_hints_for_scope.assert_called_once()
    helper.process_usage_hints.assert_called_once()


async def test_did_open_runs_diagnostics(
    fake_container: FakeContainer, fake_workspace: FakeWorkspace
) -> None:
    diagnostic_engine = MagicMock()
    diagnostic_engine.run_diagnostics = AsyncMock()
    fake_container.register(DiagnosticEngineProtocol, diagnostic_engine)

    params = types.DidOpenTextDocumentParams(
        text_document=types.TextDocumentItem(
            uri="file:///test.py",
            language_id="python",
            version=1,
            text="x = 1\n",
        )
    )

    await did_open(params)

    diagnostic_engine.run_diagnostics.assert_called_once_with(
        lsp_server, "file:///test.py", "x = 1\n"
    )


async def test_did_change_schedules_diagnostics(
    fake_container: FakeContainer, fake_workspace: FakeWorkspace
) -> None:
    diagnostic_engine = MagicMock()
    diagnostic_engine.schedule_diagnostics = MagicMock()
    fake_container.register(DiagnosticEngineProtocol, diagnostic_engine)

    params = types.DidChangeTextDocumentParams(
        text_document=types.VersionedTextDocumentIdentifier(uri="file:///test.py", version=2),
        content_changes=[],
    )

    await did_change(params)

    diagnostic_engine.schedule_diagnostics.assert_called_once_with(lsp_server, "file:///test.py")


async def test_did_save_runs_diagnostics(
    fake_container: FakeContainer, fake_workspace: FakeWorkspace
) -> None:
    diagnostic_engine = MagicMock()
    diagnostic_engine.run_diagnostics = AsyncMock()
    fake_container.register(DiagnosticEngineProtocol, diagnostic_engine)

    params = types.DidSaveTextDocumentParams(
        text_document=types.TextDocumentIdentifier(uri="file:///test.py"),
        text=None,
    )

    await did_save(params)

    diagnostic_engine.run_diagnostics.assert_called_once_with(
        lsp_server, "file:///test.py", "x = 1\n"
    )


async def test_insert_type_no_definition(
    fake_container: FakeContainer, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_jedi(monkeypatch=monkeypatch, goto_result=[], infer_result=[])

    ls = FakeLanguageServer(
        workspace=FakeWorkspace({"file:///test.py": _make_doc("file:///test.py", "x = 1\n")})
    )

    result = await insert_type(ls, ["file:///test.py", 0, 0])

    assert result["success"] is False
    assert "No variable" in result["message"]


async def test_insert_type_success(
    fake_container: FakeContainer, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeDefinition:
        def __init__(self) -> None:
            self.name = "x"
            self.type = "statement"

    _install_fake_jedi(monkeypatch, goto_result=[FakeDefinition()], infer_result=[])

    workflow = MagicMock()
    workflow.annotate_target_with_fallbacks = AsyncMock(
        return_value={
            "inferred_type": "int",
            "modified_source": "x: int = 1\n",
            "insertion_success": True,
            "error_message": None,
        }
    )
    fake_container.register(TypeAnnotationWorkflowProtocol, workflow)

    ls = FakeLanguageServer(
        workspace=FakeWorkspace({"file:///test.py": _make_doc("file:///test.py", "x = 1\n")})
    )

    result = await insert_type(ls, ["file:///test.py", 0, 0])

    assert result["success"] is True
    assert result["edits"].changes["file:///test.py"][0].new_text == "x: int = 1\n"
    workflow.annotate_target_with_fallbacks.assert_called_once()


async def test_insert_types_in_file_success(fake_container: FakeContainer) -> None:
    workflow = MagicMock()
    workflow.insert_all_types = AsyncMock(return_value=("x: int = 1\n", 1, 0, "Inserted"))
    fake_container.register(TypeAnnotationWorkflowProtocol, workflow)
    fake_container.register(Settings, Settings())

    ls = FakeLanguageServer(
        workspace=FakeWorkspace({"file:///test.py": _make_doc("file:///test.py", "x = 1\n")})
    )

    result = await insert_types_in_file(ls, ["file:///test.py"])

    assert result["success"] is True
    assert result["inserted_count"] == 1


async def test_preview_inserts_success(fake_container: FakeContainer) -> None:
    workflow = MagicMock()
    workflow.preview_insertions = AsyncMock(
        return_value={
            "total_plans": 2,
            "plan_details": [{"target": "x", "type": "int", "line": 2}],
        }
    )
    fake_container.register(TypeAnnotationWorkflowProtocol, workflow)

    ls = FakeLanguageServer(
        workspace=FakeWorkspace({"file:///test.py": _make_doc("file:///test.py", "x = 1\n")})
    )

    result = await preview_inserts(ls, ["file:///test.py"])

    assert result["success"] is True
    assert result["total_changes"] == 2
    assert result["will_insert"]
    assert result["will_insert"][0]["variable"] == "x"
    assert result["will_insert"][0]["type"] == "int"


async def test_remove_types_in_file_success(fake_container: FakeContainer) -> None:
    workflow = MagicMock()
    workflow.remove_types.return_value = (
        "x = 1\n",
        {"success": True, "removed_count": 1, "not_found": [], "skipped": []},
    )
    fake_container.register(TypeAnnotationWorkflowProtocol, workflow)

    ls = FakeLanguageServer(
        workspace=FakeWorkspace({"file:///test.py": _make_doc("file:///test.py", "x: int = 1\n")})
    )

    result = await remove_types_in_file(ls, ["file:///test.py", ["x"], False])

    assert result["success"] is True
    assert result["removed_count"] == 1
    assert result["edits"].changes["file:///test.py"][0].new_text == "x = 1\n"


async def test_remove_types_in_file_no_types(fake_container: FakeContainer) -> None:
    workflow = MagicMock()
    workflow.remove_types.return_value = (
        "x: int = 1\n",
        {"success": False, "removed_count": 0, "not_found": ["x"], "skipped": []},
    )
    fake_container.register(TypeAnnotationWorkflowProtocol, workflow)

    ls = FakeLanguageServer(
        workspace=FakeWorkspace({"file:///test.py": _make_doc("file:///test.py", "x: int = 1\n")})
    )

    result = await remove_types_in_file(ls, ["file:///test.py", ["x"], False])

    assert result["success"] is False
    assert result["removed_count"] == 0
    assert result["not_found"] == ["x"]


async def test_preview_removals_success(fake_container: FakeContainer) -> None:
    workflow = MagicMock()
    workflow.preview_removals.return_value = {
        "success": True,
        "will_remove": [{"variable": "x"}],
        "not_found": [],
        "will_skip": [],
        "total_changes": 1,
    }
    fake_container.register(TypeAnnotationWorkflowProtocol, workflow)

    ls = FakeLanguageServer(
        workspace=FakeWorkspace({"file:///test.py": _make_doc("file:///test.py", "x: int = 1\n")})
    )

    result = preview_removals(ls, ["file:///test.py", ["x"]])

    assert result["success"] is True
    assert result["total_changes"] == 1
