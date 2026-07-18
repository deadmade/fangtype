"""Tests for CodeActionHelper, in particular that inference runs off-loop."""

import threading
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock

from lsprotocol import types

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


class TestGetInsertTypeActionsOffMainThread:
    """`get_insert_type_actions` must run its Jedi inference off the event loop."""

    async def test_infer_types_runs_off_main_thread(self) -> None:
        source = "x = 1\n"
        ls = FakeLanguageServer(source)

        thread_flags: dict[str, bool] = {}

        def fake_infer_types(
            src: str, path: str | None = None, project_root: str | None = None
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

        validation_result = MagicMock()
        validation_result.is_valid = True
        type_validator = MagicMock()
        type_validator.validate_bulk = AsyncMock(return_value={"_single": validation_result})

        helper = CodeActionHelper(
            inference_engine, insertion_engine, type_validator, DocumentCache(), Settings()
        )

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

        validation_result = MagicMock()
        validation_result.is_valid = True
        type_validator = MagicMock()
        type_validator.validate_bulk = AsyncMock(return_value={"_single": validation_result})

        helper = CodeActionHelper(
            inference_engine, insertion_engine, type_validator, DocumentCache(), Settings()
        )

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
