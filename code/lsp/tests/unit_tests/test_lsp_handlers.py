"""Tests for LSP handler behavior in server.py, using the mocked-dependency lsp_server fixture."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from lsprotocol import types

from fangtype.protocols import (
    DiagnosticEngineProtocol,
    TypeValidatorProtocol,
)
from fangtype.removal import RemovalEngine
from fangtype.utils import InlayHintHelper, Settings

if TYPE_CHECKING:
    from fangtype.server import FangtypeServer


@dataclass
class FakeDocument:
    uri: str
    source: str
    version: int | None = None


class FakeWorkspace:
    def __init__(self, docs: dict[str, FakeDocument]) -> None:
        self._docs = docs

    def get_text_document(self, uri: str) -> FakeDocument:
        return self._docs[uri]


class FakeLanguageServer:
    def __init__(self, workspace: FakeWorkspace | None = None, config: list[dict] | None = None):
        self.workspace = workspace
        self._config = config

    async def workspace_configuration_async(self, params: types.ConfigurationParams):
        return self._config


def _fake_ls(
    workspace: FakeWorkspace | None = None, config: list[dict] | None = None
) -> FangtypeServer:
    """Build a FakeLanguageServer typed as the real server for command-handler calls."""
    return cast("FangtypeServer", FakeLanguageServer(workspace=workspace, config=config))


def _make_doc(uri: str, source: str) -> FakeDocument:
    return FakeDocument(uri=uri, source=source)


@pytest.fixture
def fake_workspace(lsp_server: FangtypeServer, monkeypatch: pytest.MonkeyPatch) -> FakeWorkspace:
    uri = "file:///test.py"
    docs = {uri: _make_doc(uri, "x = 1\n")}
    workspace = FakeWorkspace(docs)
    monkeypatch.setattr(lsp_server.protocol, "_workspace", workspace)
    return workspace


async def test_inlay_hints_collects_and_returns_hints(
    lsp_server: FangtypeServer, fake_workspace: FakeWorkspace
) -> None:
    from types import SimpleNamespace

    class FakeScopeTree:
        def __init__(self) -> None:
            self.scopes_by_id = {"root": object()}

    fake_inference_result = SimpleNamespace(scope_tree=FakeScopeTree())

    workflow = MagicMock()
    workflow.collect_types = AsyncMock(return_value=fake_inference_result)

    hint = types.InlayHint(
        position=types.Position(line=0, character=0),
        label=": int",
    )

    helper = MagicMock(spec=InlayHintHelper)
    helper.generate_hints_for_scope.return_value = [hint]
    helper.process_usage_hints = AsyncMock(return_value=[hint])

    lsp_server.settings = Settings()
    lsp_server.workflow = workflow
    lsp_server.inlay_hints_helper = helper

    params = types.InlayHintParams(
        text_document=types.TextDocumentIdentifier(uri="file:///test.py"),
        range=types.Range(start=types.Position(line=0, character=0), end=types.Position(0, 1)),
    )

    result = await lsp_server.inlay_hints(params)

    assert len(result) == 2
    helper.generate_hints_for_scope.assert_called_once()
    helper.process_usage_hints.assert_called_once()

    # A per-request cancel token is threaded into both inference calls; not cancelled normally.
    cav_token = workflow.collect_types.call_args.kwargs["cancel_token"]
    puh_token = helper.process_usage_hints.call_args.kwargs["cancel_token"]
    assert cav_token is not None
    assert puh_token is cav_token
    assert cav_token.cancelled() is False


async def test_did_open_runs_diagnostics(
    lsp_server: FangtypeServer, fake_workspace: FakeWorkspace
) -> None:
    diagnostic_engine = MagicMock()
    diagnostic_engine.run_diagnostics = AsyncMock()
    lsp_server.diagnostics = diagnostic_engine

    params = types.DidOpenTextDocumentParams(
        text_document=types.TextDocumentItem(
            uri="file:///test.py",
            language_id="python",
            version=1,
            text="x = 1\n",
        )
    )

    await lsp_server.did_open(params)

    diagnostic_engine.run_diagnostics.assert_called_once_with(
        lsp_server, "file:///test.py", "x = 1\n"
    )


async def test_did_open_requests_inlay_refresh(
    lsp_server: FangtypeServer, fake_workspace: FakeWorkspace
) -> None:
    diagnostic_engine = MagicMock()
    diagnostic_engine.run_diagnostics = AsyncMock()
    lsp_server.diagnostics = diagnostic_engine

    params = types.DidOpenTextDocumentParams(
        text_document=types.TextDocumentItem(
            uri="file:///test.py",
            language_id="python",
            version=1,
            text="x = 1\n",
        )
    )

    await lsp_server.did_open(params)

    # workspace_inlay_hint_refresh_async is stubbed as an AsyncMock by make_test_server.
    lsp_server.workspace_inlay_hint_refresh_async.assert_awaited_once_with(None)


async def test_did_change_schedules_diagnostics(
    lsp_server: FangtypeServer, fake_workspace: FakeWorkspace
) -> None:
    diagnostic_engine = MagicMock()
    diagnostic_engine.schedule_diagnostics = MagicMock()
    lsp_server.diagnostics = diagnostic_engine

    params = types.DidChangeTextDocumentParams(
        text_document=types.VersionedTextDocumentIdentifier(uri="file:///test.py", version=2),
        content_changes=[],
    )

    await lsp_server.did_change(params)

    diagnostic_engine.schedule_diagnostics.assert_called_once_with(lsp_server, "file:///test.py")


async def test_did_change_requests_inlay_refresh(
    lsp_server: FangtypeServer, fake_workspace: FakeWorkspace
) -> None:
    diagnostic_engine = MagicMock()
    diagnostic_engine.schedule_diagnostics = MagicMock()
    lsp_server.diagnostics = diagnostic_engine

    params = types.DidChangeTextDocumentParams(
        text_document=types.VersionedTextDocumentIdentifier(uri="file:///test.py", version=2),
        content_changes=[],
    )

    await lsp_server.did_change(params)

    diagnostic_engine.schedule_diagnostics.assert_called_once()
    # did_change refreshes inlay hints immediately (not only after the debounced diagnostics) so an
    # applied insert settles instantly instead of lingering until mypy finishes ~0.5s later.
    lsp_server.workspace_inlay_hint_refresh_async.assert_awaited_once_with(None)


async def test_did_save_runs_diagnostics(
    lsp_server: FangtypeServer, fake_workspace: FakeWorkspace
) -> None:
    diagnostic_engine = MagicMock()
    diagnostic_engine.run_diagnostics = AsyncMock()
    lsp_server.diagnostics = diagnostic_engine

    params = types.DidSaveTextDocumentParams(
        text_document=types.TextDocumentIdentifier(uri="file:///test.py"),
        text=None,
    )

    await lsp_server.did_save(params)

    diagnostic_engine.run_diagnostics.assert_called_once_with(
        lsp_server, "file:///test.py", "x = 1\n"
    )


async def test_did_save_requests_inlay_refresh(
    lsp_server: FangtypeServer, fake_workspace: FakeWorkspace
) -> None:
    diagnostic_engine = MagicMock()
    diagnostic_engine.run_diagnostics = AsyncMock()
    lsp_server.diagnostics = diagnostic_engine

    params = types.DidSaveTextDocumentParams(
        text_document=types.TextDocumentIdentifier(uri="file:///test.py"),
        text=None,
    )

    await lsp_server.did_save(params)

    # workspace_inlay_hint_refresh_async is stubbed as an AsyncMock by make_test_server.
    lsp_server.workspace_inlay_hint_refresh_async.assert_awaited_once_with(None)


async def test_inlay_refresh_swallows_unsupported_client(
    lsp_server: FangtypeServer,
    fake_workspace: FakeWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    diagnostic_engine = MagicMock()
    diagnostic_engine.run_diagnostics = AsyncMock()
    lsp_server.diagnostics = diagnostic_engine
    # A client without inlayHint.refreshSupport makes the refresh request raise.
    monkeypatch.setattr(
        lsp_server,
        "workspace_inlay_hint_refresh_async",
        AsyncMock(side_effect=RuntimeError("no refreshSupport")),
    )

    params = types.DidOpenTextDocumentParams(
        text_document=types.TextDocumentItem(
            uri="file:///test.py",
            language_id="python",
            version=1,
            text="x = 1\n",
        )
    )

    await lsp_server.did_open(params)


async def test_insert_type_no_target(lsp_server: FangtypeServer) -> None:
    workflow = MagicMock()
    workflow.annotate_at_position = AsyncMock(
        return_value={
            "name": None,
            "inferred_type": None,
            "modified_source": None,
            "insertion_success": False,
            "error_message": "No variable or expression found at cursor position",
        }
    )
    lsp_server.workflow = workflow

    ls = _fake_ls(
        workspace=FakeWorkspace({"file:///test.py": _make_doc("file:///test.py", "x = 1\n")})
    )

    result = await lsp_server.insert_type(ls, ["file:///test.py", 0, 0])

    assert result["success"] is False
    assert "No variable" in result["message"]


async def test_insert_type_success(lsp_server: FangtypeServer) -> None:
    workflow = MagicMock()
    workflow.annotate_at_position = AsyncMock(
        return_value={
            "name": "x",
            "inferred_type": "int",
            "modified_source": "x: int = 1\n",
            "insertion_success": True,
            "error_message": None,
            "message": "Inserted type annotation: x: int",
        }
    )
    lsp_server.workflow = workflow

    ls = _fake_ls(
        workspace=FakeWorkspace({"file:///test.py": _make_doc("file:///test.py", "x = 1\n")})
    )

    result = await lsp_server.insert_type(ls, ["file:///test.py", 0, 0])

    assert result["success"] is True
    assert result["edits"].document_changes[0].edits[0].new_text == "x: int = 1\n"
    assert "x: int" in result["message"]
    workflow.annotate_at_position.assert_called_once()

    passed = workflow.annotate_at_position.call_args.kwargs["cancel_token"]
    assert passed is not None
    assert passed.cancelled() is False


async def test_insert_type_resolves_target_via_workflow_not_jedi(
    lsp_server: FangtypeServer,
) -> None:
    """insert_type is a thin adapter: it succeeds via the workflow with no fake jedi installed."""
    workflow = MagicMock()
    workflow.annotate_at_position = AsyncMock(
        return_value={
            "name": "x",
            "inferred_type": "int",
            "modified_source": "x: int = 1\n",
            "insertion_success": True,
            "error_message": None,
            "message": "Inserted type annotation: x: int",
        }
    )
    lsp_server.workflow = workflow

    ls = _fake_ls(
        workspace=FakeWorkspace({"file:///test.py": _make_doc("file:///test.py", "x = 1\n")})
    )

    # Behavioral guard against re-introducing the direct-Jedi goto leak: insert_type must resolve
    # the cursor via the workflow only, so a real jedi.Script call from the handler blows up here.
    with patch(
        "jedi.Script", side_effect=AssertionError("insert_type must not call Jedi directly")
    ):
        result = await lsp_server.insert_type(ls, ["file:///test.py", 0, 0])
    assert result["success"] is True


async def test_insert_types_in_file_success(lsp_server: FangtypeServer) -> None:
    workflow = MagicMock()
    workflow.insert_all_types = AsyncMock(
        return_value=("x: int = 1\n", 1, {"selected": 1}, "Inserted")
    )
    lsp_server.workflow = workflow

    ls = _fake_ls(
        workspace=FakeWorkspace({"file:///test.py": _make_doc("file:///test.py", "x = 1\n")})
    )

    result = await lsp_server.insert_types_in_file(ls, ["file:///test.py"])

    assert result["success"] is True
    assert result["inserted_count"] == 1
    assert result["variable_drop_reasons"] == {"selected": 1}

    passed = workflow.insert_all_types.call_args.kwargs["cancel_token"]
    assert passed is not None
    assert passed.cancelled() is False


async def test_insert_types_in_file_attribute_only_success(lsp_server: FangtypeServer) -> None:
    """Bug #3: attribute-only insertion (inserted_count==1) still succeeds with a WorkspaceEdit."""
    workflow = MagicMock()
    annotated = "class C:\n    def __init__(self, width):\n        self.width: int = width\n"
    workflow.insert_all_types = AsyncMock(
        return_value=(annotated, 1, {}, "Inserted 1 type annotations")
    )
    lsp_server.workflow = workflow

    ls = _fake_ls(
        workspace=FakeWorkspace(
            {
                "file:///test.py": _make_doc(
                    "file:///test.py",
                    "class C:\n    def __init__(self, width):\n        self.width = width\n",
                )
            }
        )
    )

    result = await lsp_server.insert_types_in_file(ls, ["file:///test.py"])

    assert result["success"] is True
    assert result["edits"] is not None
    assert result["inserted_count"] == 1


async def test_preview_inserts_success(lsp_server: FangtypeServer) -> None:
    workflow = MagicMock()
    workflow.preview_insertions = AsyncMock(
        return_value={
            "will_insert": [{"variable": "x", "type": "int", "line": 2}],
            "total_changes": 2,
        }
    )
    lsp_server.workflow = workflow

    ls = _fake_ls(
        workspace=FakeWorkspace({"file:///test.py": _make_doc("file:///test.py", "x = 1\n")})
    )

    result = await lsp_server.preview_inserts(ls, ["file:///test.py"])

    assert result["success"] is True
    assert result["total_changes"] == 2
    assert result["will_insert"]
    assert result["will_insert"][0]["variable"] == "x"
    assert result["will_insert"][0]["type"] == "int"

    passed = workflow.preview_insertions.call_args.kwargs["cancel_token"]
    assert passed is not None
    assert passed.cancelled() is False


# Task C1: on cancel, handlers cancel the per-request token; same token reads cancelled()==True.


async def test_inlay_hints_cancel_cancels_token(
    lsp_server: FangtypeServer, fake_workspace: FakeWorkspace
) -> None:
    workflow = MagicMock()
    workflow.collect_types = AsyncMock(side_effect=asyncio.CancelledError)
    helper = MagicMock(spec=InlayHintHelper)

    lsp_server.settings = Settings()
    lsp_server.workflow = workflow
    lsp_server.inlay_hints_helper = helper

    params = types.InlayHintParams(
        text_document=types.TextDocumentIdentifier(uri="file:///test.py"),
        range=types.Range(start=types.Position(line=0, character=0), end=types.Position(0, 1)),
    )

    result = await lsp_server.inlay_hints(params)

    assert result == []
    passed = workflow.collect_types.call_args.kwargs["cancel_token"]
    assert passed is not None
    assert passed.cancelled() is True  # handler called cancel_token.cancel()


@pytest.mark.parametrize(
    ("workflow_attr", "invoke"),
    [
        pytest.param(
            "annotate_at_position",
            lambda s, ls: s.insert_type(ls, ["file:///test.py", 0, 0]),
            id="insert_type",
        ),
        pytest.param(
            "insert_all_types",
            lambda s, ls: s.insert_types_in_file(ls, ["file:///test.py"]),
            id="insert_types_in_file",
        ),
        pytest.param(
            "preview_insertions",
            lambda s, ls: s.preview_inserts(ls, ["file:///test.py"]),
            id="preview_inserts",
        ),
    ],
)
async def test_command_handler_cancel_cancels_token(
    lsp_server: FangtypeServer, workflow_attr: str, invoke
) -> None:
    workflow = MagicMock()
    setattr(workflow, workflow_attr, AsyncMock(side_effect=asyncio.CancelledError))
    lsp_server.workflow = workflow

    ls = _fake_ls(
        workspace=FakeWorkspace({"file:///test.py": _make_doc("file:///test.py", "x = 1\n")})
    )

    result = await invoke(lsp_server, ls)

    assert result["success"] is False
    passed = getattr(workflow, workflow_attr).call_args.kwargs["cancel_token"]
    assert passed is not None
    assert passed.cancelled() is True


async def test_code_actions_forwards_a_cancel_token(lsp_server: FangtypeServer) -> None:
    """S6.5: code_actions must build a per-request cancel token and forward it to the helper."""
    helper = MagicMock()
    helper.get_insert_type_actions = AsyncMock(return_value=[])
    lsp_server.code_action_helper = helper

    params = types.CodeActionParams(
        text_document=types.TextDocumentIdentifier(uri="file:///test.py"),
        range=types.Range(start=types.Position(line=0, character=0), end=types.Position(0, 1)),
        context=types.CodeActionContext(diagnostics=[]),
    )

    result = await lsp_server.code_actions(params)

    assert result == []
    passed = helper.get_insert_type_actions.call_args.kwargs["cancel_token"]
    assert passed is not None
    assert passed.cancelled() is False


async def test_code_actions_cancel_cancels_token(lsp_server: FangtypeServer) -> None:
    """S6.5: on cancel, code_actions cancels the same token it handed to the helper."""
    helper = MagicMock()
    helper.get_insert_type_actions = AsyncMock(side_effect=asyncio.CancelledError)
    lsp_server.code_action_helper = helper

    params = types.CodeActionParams(
        text_document=types.TextDocumentIdentifier(uri="file:///test.py"),
        range=types.Range(start=types.Position(line=0, character=0), end=types.Position(0, 1)),
        context=types.CodeActionContext(diagnostics=[]),
    )

    result = await lsp_server.code_actions(params)

    assert result == []
    passed = helper.get_insert_type_actions.call_args.kwargs["cancel_token"]
    assert passed is not None
    assert passed.cancelled() is True


async def test_remove_types_in_file_success(lsp_server: FangtypeServer) -> None:
    workflow = MagicMock()
    workflow.remove_types.return_value = (
        "x = 1\n",
        {
            "success": True,
            "removed_count": 1,
            "not_found": [],
            "will_skip": [],
            "message": "Removed 1 type annotation(s).",
        },
    )
    lsp_server.workflow = workflow

    ls = _fake_ls(
        workspace=FakeWorkspace({"file:///test.py": _make_doc("file:///test.py", "x: int = 1\n")})
    )

    result = await lsp_server.remove_types_in_file(ls, ["file:///test.py", ["x"], False])

    assert result["success"] is True
    assert result["removed_count"] == 1
    assert result["edits"].document_changes[0].edits[0].new_text == "x = 1\n"


async def test_remove_types_in_file_no_types(lsp_server: FangtypeServer) -> None:
    workflow = MagicMock()
    workflow.remove_types.return_value = (
        "x: int = 1\n",
        {
            "success": False,
            "removed_count": 0,
            "not_found": ["x"],
            "will_skip": [],
            "message": "No type annotations found to remove",
        },
    )
    lsp_server.workflow = workflow

    ls = _fake_ls(
        workspace=FakeWorkspace({"file:///test.py": _make_doc("file:///test.py", "x: int = 1\n")})
    )

    result = await lsp_server.remove_types_in_file(ls, ["file:///test.py", ["x"], False])

    assert result["success"] is False
    assert result["removed_count"] == 0
    assert result["not_found"] == ["x"]


async def test_remove_types_in_file_reads_will_skip_directly(lsp_server: FangtypeServer) -> None:
    """remove_types_in_file reads will_skip off result_info and republishes it as skipped."""
    workflow = MagicMock()
    workflow.remove_types.return_value = (
        "x = 1\ny: int = 2\n",
        {
            "success": True,
            "removed_count": 1,
            "not_found": [],
            "will_skip": [{"variable": "y", "reason": "no value", "line": 2}],
            "message": "Removed 1 type annotation(s). Skipped 1 variable(s) without values.",
        },
    )
    lsp_server.workflow = workflow

    ls = _fake_ls(
        workspace=FakeWorkspace(
            {"file:///test.py": _make_doc("file:///test.py", "x: int = 1\ny: int\n")}
        )
    )

    result = await lsp_server.remove_types_in_file(ls, ["file:///test.py", None, False])

    assert result["success"] is True
    assert result["skipped"] == [{"variable": "y", "reason": "no value", "line": 2}]


def test_preview_removals_success(lsp_server: FangtypeServer) -> None:
    # Handler routes through the workflow (backed by the real RemovalEngine), exercised end-to-end.
    workflow = MagicMock()
    workflow.preview_removals.side_effect = lambda source, variables, include_functions=False: (
        RemovalEngine().preview_removals(source, variables, include_functions)
    )
    lsp_server.workflow = workflow

    ls = _fake_ls(
        workspace=FakeWorkspace({"file:///test.py": _make_doc("file:///test.py", "x: int = 1\n")})
    )

    result = lsp_server.preview_removals(ls, ["file:///test.py", ["x"]])

    assert result["success"] is True
    assert result["total_changes"] == 1
    workflow.preview_removals.assert_called_once_with("x: int = 1\n", ["x"], False)


def test_preview_removals_forwards_include_functions(lsp_server: FangtypeServer) -> None:
    workflow = MagicMock()
    workflow.preview_removals.return_value = {
        "success": True,
        "will_remove": [],
        "total_changes": 0,
        "will_skip": [],
        "not_found": [],
    }
    lsp_server.workflow = workflow
    ls = _fake_ls(
        workspace=FakeWorkspace({"file:///test.py": _make_doc("file:///test.py", "x: int = 1\n")})
    )

    lsp_server.preview_removals(ls, ["file:///test.py", None, True])

    workflow.preview_removals.assert_called_once_with("x: int = 1\n", None, True)


def test_on_shutdown_calls_validator_close_directly(lsp_server: FangtypeServer) -> None:
    """Task 13 item 1: on_shutdown calls validator.close() directly (no getattr reflection)."""
    validator = MagicMock(spec=TypeValidatorProtocol)
    lsp_server.validator = validator

    lsp_server.on_shutdown()

    validator.close.assert_called_once_with()


def test_on_shutdown_swallows_close_exceptions(lsp_server: FangtypeServer) -> None:
    """A failure releasing the validator's resources must never block shutdown."""
    validator = MagicMock(spec=TypeValidatorProtocol)
    validator.close.side_effect = RuntimeError("boom")
    lsp_server.validator = validator

    lsp_server.on_shutdown()  # must not raise

    validator.close.assert_called_once_with()


async def test_did_close_cancels_pending_diagnostics(lsp_server: FangtypeServer) -> None:
    """Task 13 item 2: closing a document cancels/pops its pending debounce timer."""
    diagnostic_engine = MagicMock(spec=DiagnosticEngineProtocol)
    lsp_server.diagnostics = diagnostic_engine

    params = types.DidCloseTextDocumentParams(
        text_document=types.TextDocumentIdentifier(uri="file:///test.py")
    )
    await lsp_server.did_close(params)

    diagnostic_engine.cancel_pending.assert_called_once_with("file:///test.py")
