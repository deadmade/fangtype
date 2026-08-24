"""Tests for CodeActionHelper: inference off-loop, and the assignability gate on the lightbulb."""

import threading
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock

from lsprotocol import types

from fangtype.cancellation import CancellationToken
from fangtype.utils.code_action_helper import CodeActionHelper
from fangtype.utils.document_cache import DocumentCache
from fangtype.utils.settings import Settings

if TYPE_CHECKING:
    from pygls.lsp.server import LanguageServer


class FakeDocument:
    def __init__(self, source: str) -> None:
        self.source = source
        self.version: int | None = None


class FakeWorkspace:
    def __init__(self, source: str) -> None:
        self._source = source

    def get_text_document(self, uri: str) -> FakeDocument:
        return FakeDocument(self._source)


class FakeLanguageServer:
    def __init__(self, source: str) -> None:
        self.workspace = FakeWorkspace(source)


def _make_params(start_line: int = 0) -> types.CodeActionParams:
    return types.CodeActionParams(
        text_document=types.TextDocumentIdentifier(uri="file:///test.py"),
        range=types.Range(
            start=types.Position(line=start_line, character=0),
            end=types.Position(line=start_line, character=5),
        ),
        context=types.CodeActionContext(diagnostics=[]),
    )


def _make_helper(
    inference_engine: MagicMock,
    insertion_engine: MagicMock,
    settings: Settings | None = None,
) -> CodeActionHelper:
    """Build the helper with a workflow whose gate delegates straight to `insertion_engine`.

    The gate itself is exercised against real mypy in TestCodeActionAssignabilityGate below; here
    it stands aside so these tests keep asserting on the insertion engine as they did.
    """
    workflow = MagicMock()
    workflow.insert_with_assignability_gate = AsyncMock(
        side_effect=lambda targets, source: insertion_engine.insert(targets, source)
    )
    return CodeActionHelper(
        inference_engine,
        insertion_engine,
        DocumentCache(),
        settings or Settings(),
        workflow,
    )


class TestGetInsertTypeActionsOffMainThread:
    """`get_insert_type_actions` must run its Jedi inference off the event loop."""

    async def test_infer_types_runs_off_main_thread(self) -> None:
        source = "x = 1\n"
        ls = FakeLanguageServer(source)

        thread_flags: dict[str, bool] = {}

        def fake_infer_types(
            src: str,
            path: str | None = None,
            project_root: str | None = None,
            cancel_token: object | None = None,
        ) -> MagicMock:
            thread_flags["is_main"] = threading.current_thread() is threading.main_thread()
            result = MagicMock()
            result.get_variable_insertions.return_value = {(0, "x"): "int"}
            return result

        inference_engine = MagicMock()
        inference_engine.infer_types = MagicMock(side_effect=fake_infer_types)

        insertion_engine = MagicMock()
        insert_result = MagicMock()
        insert_result.success = True
        insert_result.modified_source = "x: int = 1\n"
        insertion_engine.insert.return_value = insert_result

        helper = _make_helper(inference_engine, insertion_engine)

        actions = await helper.get_insert_type_actions(
            cast("LanguageServer", ls), _make_params(start_line=0)
        )

        assert "is_main" in thread_flags, "infer_types was never called"
        assert thread_flags["is_main"] is False
        assert len(actions) == 1
        assert "int" in actions[0].title


class TestGetInsertTypeActionsClickedOccurrence:
    """`get_insert_type_actions` must annotate the CLICKED occurrence, not the min line."""

    async def test_repeated_name_annotates_clicked_line_not_min_line(self) -> None:
        # Clicking `x`'s line-3 occurrence must annotate line 3, not the min assignment line.
        source = "x = 1\n\nx = 2\n"
        ls = FakeLanguageServer(source)

        inference_engine = MagicMock()
        inference_result = MagicMock()
        inference_result.get_variable_insertions.return_value = {(2, "x"): "str"}
        inference_engine.infer_types = MagicMock(return_value=inference_result)

        insertion_engine = MagicMock()
        insert_result = MagicMock()
        insert_result.success = True
        insert_result.modified_source = "x = 1\n\nx: str = 2\n"
        insertion_engine.insert.return_value = insert_result

        helper = _make_helper(inference_engine, insertion_engine)

        actions = await helper.get_insert_type_actions(
            cast("LanguageServer", ls), _make_params(start_line=2)
        )

        assert len(actions) == 1
        assert "str" in actions[0].title

        insertion_engine.insert.assert_called_once()
        targets = insertion_engine.insert.call_args.args[0]
        assert len(targets) == 1
        target = targets[0]
        assert target.location.line == 3, (
            "Insertion must land on the clicked occurrence (line 3), not the min "
            f"assignment line; got {target.location.line}"
        )


class TestGetInsertTypeActionsCancelToken:
    """S6.5: a caller-supplied cancel token must reach `infer_types`, like every other call site."""

    async def test_cancel_token_is_forwarded_to_infer_types(self) -> None:
        source = "x = 1\n"
        ls = FakeLanguageServer(source)
        cancel_token = CancellationToken()

        inference_result = MagicMock()
        inference_result.get_variable_insertions.return_value = {}
        inference_engine = MagicMock()
        inference_engine.infer_types = MagicMock(return_value=inference_result)

        insertion_engine = MagicMock()

        helper = _make_helper(inference_engine, insertion_engine)

        await helper.get_insert_type_actions(
            cast("LanguageServer", ls), _make_params(start_line=0), cancel_token=cancel_token
        )

        inference_engine.infer_types.assert_called_once()
        assert inference_engine.infer_types.call_args.kwargs["cancel_token"] is cancel_token

    async def test_no_cancel_token_defaults_to_none(self) -> None:
        """Existing callers that don't pass a token must keep working (backward-compatible)."""
        source = "x = 1\n"
        ls = FakeLanguageServer(source)

        inference_result = MagicMock()
        inference_result.get_variable_insertions.return_value = {}
        inference_engine = MagicMock()
        inference_engine.infer_types = MagicMock(return_value=inference_result)

        insertion_engine = MagicMock()

        helper = _make_helper(inference_engine, insertion_engine)

        await helper.get_insert_type_actions(cast("LanguageServer", ls), _make_params(start_line=0))

        inference_engine.infer_types.assert_called_once()
        assert inference_engine.infer_types.call_args.kwargs["cancel_token"] is None


def _edit_text(action: types.CodeAction) -> str:
    """The full-document replacement the action carries."""
    assert action.edit is not None
    document_changes = action.edit.document_changes
    assert document_changes is not None
    document_edit = document_changes[0]
    assert isinstance(document_edit, types.TextDocumentEdit)
    edit = document_edit.edits[0]
    assert isinstance(edit, types.TextEdit)
    return edit.new_text


def _real_helper(source_types: dict[tuple[int, str], str], settings: Settings) -> CodeActionHelper:
    """Helper wired to a real InsertionEngine, a real MypyTypeValidator and a real workflow."""
    from fangtype.insertion import InsertionEngine
    from fangtype.removal import RemovalEngine
    from fangtype.validation.mypy_validator import MypyTypeValidator
    from fangtype.workflow import TypeAnnotationWorkflow

    inference_result = MagicMock()
    inference_result.get_variable_insertions.return_value = source_types
    inference_result.get_import_hints.return_value = {}

    inference = MagicMock()
    inference.infer_types.return_value = inference_result

    insertion_engine = InsertionEngine()
    validator = MypyTypeValidator(settings)
    workflow = TypeAnnotationWorkflow(
        inference,
        insertion_engine,
        RemovalEngine(),
        validator,
        settings,
        DocumentCache(),
    )
    return CodeActionHelper(inference, insertion_engine, DocumentCache(), settings, workflow)


class TestCodeActionAssignabilityGate:
    """The lightbulb runs the same full-file mypy gate the insert requests run.

    The gate reads the annotation against its real right-hand side in the rendered file, so a
    wrong ``int`` for a name holding a string leaves no action to offer.
    """

    async def test_wrong_type_is_not_offered(self) -> None:
        """x="s" wrongly inferred int must yield no action at all (gate ON, the default)."""
        settings = Settings()
        source = 'x = "s"\n'
        helper = _real_helper({(0, "x"): "int"}, settings)

        actions = await helper.get_insert_type_actions(
            cast("LanguageServer", FakeLanguageServer(source)), _make_params(start_line=0)
        )

        assert actions == []

    async def test_correct_type_is_still_offered(self) -> None:
        """The gate must not cost a correct annotation its lightbulb."""
        settings = Settings()
        source = "x = 3\n"
        helper = _real_helper({(0, "x"): "int"}, settings)

        actions = await helper.get_insert_type_actions(
            cast("LanguageServer", FakeLanguageServer(source)), _make_params(start_line=0)
        )

        assert len(actions) == 1
        assert "x: int = 3" in _edit_text(actions[0])

    async def test_gate_off_offers_even_the_wrong_type(self) -> None:
        """With mypy_enabled False the pre-change behaviour stands, matching the insert path."""
        settings = Settings()
        settings.mypy_enabled = False
        source = 'x = "s"\n'
        helper = _real_helper({(0, "x"): "int"}, settings)

        actions = await helper.get_insert_type_actions(
            cast("LanguageServer", FakeLanguageServer(source)), _make_params(start_line=0)
        )

        assert len(actions) == 1
        assert "x: int" in _edit_text(actions[0])


class TestCodeActionForwardReference:
    """A name that binds after the annotated statement has to be written as a PEP 484 string."""

    async def test_later_bound_class_is_quoted(self) -> None:
        settings = Settings()
        source = (
            'def make() -> "Node":\n'
            "    return Node()\n"
            "\n\n"
            "node = make()\n"
            "\n\n"
            "class Node:\n"
            "    pass\n"
        )
        helper = _real_helper({(4, "node"): "Node"}, settings)

        actions = await helper.get_insert_type_actions(
            cast("LanguageServer", FakeLanguageServer(source)), _make_params(start_line=4)
        )

        assert len(actions) == 1
        assert 'node: "Node" = make()' in _edit_text(actions[0])
