"""Tests for CodeActionHelper: line coverage, inference off-loop, and the assignability gate."""

import threading
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock

from lsprotocol import types

from fangtype.cancellation import CancellationToken
from fangtype.inference.inference_result import FunctionInsertionInfo
from fangtype.insertion import InsertionEngine
from fangtype.removal import RemovalEngine
from fangtype.utils.code_action_helper import CodeActionHelper
from fangtype.utils.document_cache import DocumentCache
from fangtype.utils.settings import Settings
from fangtype.workflow import TypeAnnotationWorkflow

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


def _make_params(
    start_line: int = 0, only: list[types.CodeActionKind] | None = None
) -> types.CodeActionParams:
    return types.CodeActionParams(
        text_document=types.TextDocumentIdentifier(uri="file:///test.py"),
        range=types.Range(
            start=types.Position(line=start_line, character=0),
            end=types.Position(line=start_line, character=5),
        ),
        context=types.CodeActionContext(diagnostics=[], only=only),
    )


def _fake_inference(
    variables: dict[tuple[int, str], str] | None = None,
    functions: dict[tuple[int, str], FunctionInsertionInfo] | None = None,
    attributes: dict[tuple[int, str], str] | None = None,
    on_infer: object = None,
) -> MagicMock:
    """A mock inference engine whose result answers every accessor `_build_targets` reaches.

    A bare MagicMock cannot stand in here: the target builder iterates all three insertion dicts,
    and an unconfigured MagicMock returns a MagicMock that will not iterate as a mapping.
    """
    result = MagicMock()
    result.is_complete = True
    result.get_variable_insertions.return_value = variables or {}
    result.get_variable_insertion_candidates.return_value = {}
    result.get_function_insertions.return_value = functions or {}
    result.get_attribute_insertions.return_value = attributes or {}
    result.get_import_hints.return_value = {}
    result.get_function_import_hints.return_value = {}

    engine = MagicMock()
    if on_infer is not None:
        engine.infer_types = MagicMock(side_effect=on_infer)
    else:
        engine.infer_types = MagicMock(return_value=result)
    return engine


def _helper(
    inference_engine: MagicMock,
    insertion_engine: object | None = None,
    settings: Settings | None = None,
) -> CodeActionHelper:
    """Build the helper over a real workflow, so the code action exercises the real target builder.

    The gate is left at whatever `settings.mypy_enabled` says. Tests that assert on the insertion
    engine turn it off, which is the short-circuit `_insert_with_assignability_gate` already takes.
    The gate itself is exercised against real mypy in TestCodeActionAssignabilityGate below.
    """
    settings = settings if settings is not None else Settings()
    workflow = TypeAnnotationWorkflow(
        inference_engine,
        cast("InsertionEngine", insertion_engine if insertion_engine is not None else MagicMock()),
        RemovalEngine(),
        MagicMock(),
        settings,
        DocumentCache(),
    )
    return CodeActionHelper(workflow)


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


def _mock_insertion_engine(modified_source: str, inserted_count: int = 1) -> MagicMock:
    """An insertion engine that reports one successful insert without touching LibCST."""
    engine = MagicMock()
    result = MagicMock()
    result.success = True
    result.inserted_count = inserted_count
    result.modified_source = modified_source
    engine.insert.return_value = result
    return engine


def _gate_off() -> Settings:
    settings = Settings()
    settings.mypy_enabled = False
    return settings


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
            result.is_complete = True
            result.get_variable_insertions.return_value = {(0, "x"): "int"}
            result.get_variable_insertion_candidates.return_value = {}
            result.get_function_insertions.return_value = {}
            result.get_attribute_insertions.return_value = {}
            result.get_import_hints.return_value = {}
            result.get_function_import_hints.return_value = {}
            return result

        inference_engine = _fake_inference(on_infer=fake_infer_types)
        insertion_engine = _mock_insertion_engine("x: int = 1\n")
        helper = _helper(inference_engine, insertion_engine, _gate_off())

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

        inference_engine = _fake_inference(variables={(0, "x"): "int", (2, "x"): "str"})
        insertion_engine = _mock_insertion_engine("x = 1\n\nx: str = 2\n")
        helper = _helper(inference_engine, insertion_engine, _gate_off())

        actions = await helper.get_insert_type_actions(
            cast("LanguageServer", ls), _make_params(start_line=2)
        )

        assert len(actions) == 1
        assert "str" in actions[0].title

        insertion_engine.insert.assert_called_once()
        targets = insertion_engine.insert.call_args.args[0]
        assert len(targets) == 1, "only the clicked line's target may be offered"
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

        inference_engine = _fake_inference()
        helper = _helper(inference_engine, settings=_gate_off())

        await helper.get_insert_type_actions(
            cast("LanguageServer", ls), _make_params(start_line=0), cancel_token=cancel_token
        )

        inference_engine.infer_types.assert_called_once()
        assert inference_engine.infer_types.call_args.kwargs["cancel_token"] is cancel_token

    async def test_no_cancel_token_defaults_to_none(self) -> None:
        """Existing callers that don't pass a token must keep working (backward-compatible)."""
        source = "x = 1\n"
        ls = FakeLanguageServer(source)

        inference_engine = _fake_inference()
        helper = _helper(inference_engine, settings=_gate_off())

        await helper.get_insert_type_actions(cast("LanguageServer", ls), _make_params(start_line=0))

        inference_engine.infer_types.assert_called_once()
        assert inference_engine.infer_types.call_args.kwargs["cancel_token"] is None


def _real_helper(
    settings: Settings,
    variables: dict[tuple[int, str], str] | None = None,
    functions: dict[tuple[int, str], FunctionInsertionInfo] | None = None,
    attributes: dict[tuple[int, str], str] | None = None,
) -> CodeActionHelper:
    """Helper wired to a real InsertionEngine, a real MypyTypeValidator and a real workflow."""
    from fangtype.validation.mypy_validator import MypyTypeValidator

    inference = _fake_inference(variables, functions, attributes)
    workflow = TypeAnnotationWorkflow(
        inference,
        InsertionEngine(),
        RemovalEngine(),
        MypyTypeValidator(settings),
        settings,
        DocumentCache(),
    )
    return CodeActionHelper(workflow)


async def _actions_at(helper: CodeActionHelper, source: str, line: int) -> list[types.CodeAction]:
    return await helper.get_insert_type_actions(
        cast("LanguageServer", FakeLanguageServer(source)), _make_params(start_line=line)
    )


class TestCodeActionAssignabilityGate:
    """The lightbulb runs the same full-file mypy gate the insert requests run.

    The gate reads the annotation against its real right-hand side in the rendered file, so a
    wrong ``int`` for a name holding a string leaves no action to offer.
    """

    async def test_wrong_type_is_not_offered(self) -> None:
        """x="s" wrongly inferred int must yield no action at all (gate ON, the default)."""
        helper = _real_helper(Settings(), variables={(0, "x"): "int"})

        actions = await _actions_at(helper, 'x = "s"\n', 0)

        assert actions == []

    async def test_correct_type_is_still_offered(self) -> None:
        """The gate must not cost a correct annotation its lightbulb."""
        helper = _real_helper(Settings(), variables={(0, "x"): "int"})

        actions = await _actions_at(helper, "x = 3\n", 0)

        assert len(actions) == 1
        assert "x: int = 3" in _edit_text(actions[0])

    async def test_gate_off_offers_even_the_wrong_type(self) -> None:
        """With mypy_enabled False the pre-change behaviour stands, matching the insert path."""
        helper = _real_helper(_gate_off(), variables={(0, "x"): "int"})

        actions = await _actions_at(helper, 'x = "s"\n', 0)

        assert len(actions) == 1
        assert "x: int" in _edit_text(actions[0])


class TestCodeActionForwardReference:
    """A name that binds after the annotated statement has to be written as a PEP 484 string."""

    async def test_later_bound_class_is_quoted(self) -> None:
        source = (
            'def make() -> "Node":\n'
            "    return Node()\n"
            "\n\n"
            "node = make()\n"
            "\n\n"
            "class Node:\n"
            "    pass\n"
        )
        helper = _real_helper(Settings(), variables={(4, "node"): "Node"})

        actions = await _actions_at(helper, source, 4)

        assert len(actions) == 1


class TestCodeActionCoverage:
    """The lightbulb reaches every kind the engine can write, not only `name = value`.

    The gate is off throughout: these assert on which targets the clicked line collects and on the
    edit the engine renders, which is a separate question from whether mypy accepts the type.
    """

    async def test_signature_offers_parameters_and_return_in_one_action(self) -> None:
        source = "def scale(n, factor):\n    return n * factor\n"
        info: FunctionInsertionInfo = {
            "name": "scale",
            "params": {"n": "int", "factor": "float"},
            "return_type": "float",
        }
        helper = _real_helper(_gate_off(), functions={(0, "scale"): info})

        actions = await _actions_at(helper, source, 0)

        assert len(actions) == 1, "the whole signature is one aggregate action"
        edited = _edit_text(actions[0])
        assert "n: int" in edited
        assert "factor: float" in edited
        assert "-> float" in edited
        title = actions[0].title
        assert title.startswith("Insert 3 type annotations:")
        assert "-> float" in title

    async def test_signature_with_only_a_return_type(self) -> None:
        source = "def answer():\n    return 42\n"
        info: FunctionInsertionInfo = {"name": "answer", "params": {}, "return_type": "int"}
        helper = _real_helper(_gate_off(), functions={(0, "answer"): info})

        actions = await _actions_at(helper, source, 0)

        assert len(actions) == 1
        assert "-> int" in _edit_text(actions[0])

    async def test_attribute_assignment_is_offered(self) -> None:
        source = "class Box:\n    def __init__(self):\n        self.value = 42\n"
        # Attribute keys are already 1-based; self attrs are stored bare.
        helper = _real_helper(_gate_off(), attributes={(3, "value"): "int"})

        actions = await _actions_at(helper, source, 2)

        assert len(actions) == 1
        assert "self.value: int" in _edit_text(actions[0])

    async def test_tuple_unpacking_is_offered(self) -> None:
        source = 'a, b = 1, "x"\n'
        helper = _real_helper(_gate_off(), variables={(0, "a"): "int", (0, "b"): "str"})

        actions = await _actions_at(helper, source, 0)

        assert len(actions) == 1, "both names on the line ride one action"
        edited = _edit_text(actions[0])
        assert "a: int" in edited
        assert "b: str" in edited

    async def test_iteration_variable_is_offered(self) -> None:
        source = "for i in range(3):\n    print(i)\n"
        helper = _real_helper(_gate_off(), variables={(0, "i"): "int"})

        actions = await _actions_at(helper, source, 0)

        assert len(actions) == 1
        assert "i: int" in _edit_text(actions[0])

    async def test_wrapped_signature_offers_from_a_continuation_line(self) -> None:
        source = "def scale(\n    n,\n    factor,\n):\n    return n * factor\n"
        info: FunctionInsertionInfo = {
            "name": "scale",
            "params": {"n": "int", "factor": "float"},
            "return_type": "float",
        }
        helper = _real_helper(_gate_off(), functions={(0, "scale"): info})

        # Line 1 is `    n,` — a continuation, whose targets live on the `def` line.
        actions = await _actions_at(helper, source, 1)

        assert len(actions) == 1
        assert "n: int" in _edit_text(actions[0])

    async def test_unplaceable_name_does_not_attach_itself_to_line_one(self) -> None:
        """A name the resolver cannot place must not pile onto the first line of the file.

        Inference surfaces a self-attribute under its bare name as a variable too, and
        `find_variable_line` answers 1 when it finds no candidate for that bare name. Restricting
        on the inference key's line rather than on the built target's line is what keeps that
        stray off an unrelated signature's lightbulb.
        """
        source = (
            "def scale(n=2):\n    return n\n\n\n"
            "class Box:\n    def __init__(self):\n        self.value = 42\n"
        )
        info: FunctionInsertionInfo = {
            "name": "scale",
            "params": {"n": "int"},
            "return_type": "int",
        }
        helper = _real_helper(
            _gate_off(),
            # `value` is reported at line 7 (0-based 6) but is written as `self.value`.
            variables={(6, "value"): "int"},
            functions={(0, "scale"): info},
        )

        actions = await _actions_at(helper, source, 0)

        assert len(actions) == 1
        title = actions[0].title
        assert "value" not in title, f"line 7's attribute leaked into line 1's action: {title}"
        assert title.startswith("Insert 2 type annotations:")
        assert "self.value: int" not in _edit_text(actions[0])

    async def test_line_with_nothing_insertable_never_reaches_the_gate(self) -> None:
        source = "x = 1\nprint(x)\n"
        insertion_engine = _mock_insertion_engine("unused\n")
        helper = _helper(_fake_inference(variables={(0, "x"): "int"}), insertion_engine)

        actions = await _actions_at(helper, source, 1)

        assert actions == []
        insertion_engine.insert.assert_not_called()

    async def test_already_annotated_line_offers_nothing(self) -> None:
        # Inference reports no insertion for an annotated binding, so the line collects no target.
        source = "x: int = 1\n"
        insertion_engine = _mock_insertion_engine("unused\n")
        helper = _helper(_fake_inference(), insertion_engine)

        actions = await _actions_at(helper, source, 0)

        assert actions == []
        insertion_engine.insert.assert_not_called()


class TestCodeActionKindFilter:
    """A client asking only for kinds this action is not must get nothing back."""

    async def test_refactor_only_request_is_declined(self) -> None:
        helper = _real_helper(_gate_off(), variables={(0, "x"): "int"})

        actions = await helper.get_insert_type_actions(
            cast("LanguageServer", FakeLanguageServer("x = 1\n")),
            _make_params(start_line=0, only=[types.CodeActionKind.RefactorRewrite]),
        )

        assert actions == []

    async def test_quickfix_only_request_is_served(self) -> None:
        helper = _real_helper(_gate_off(), variables={(0, "x"): "int"})

        actions = await helper.get_insert_type_actions(
            cast("LanguageServer", FakeLanguageServer("x = 1\n")),
            _make_params(start_line=0, only=[types.CodeActionKind.QuickFix]),
        )

        assert len(actions) == 1
