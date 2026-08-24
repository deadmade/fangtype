"""Tests for type annotation workflow orchestration."""

from unittest.mock import AsyncMock, MagicMock

import pytest

import fangtype.workflow as workflow_module
from fangtype.inference.inference_result import FunctionInsertionInfo
from fangtype.insertion.types import TargetType
from fangtype.utils.document_cache import DocumentCache
from fangtype.utils.settings import Settings
from fangtype.validation.mypy_validator import TypeValidationResult
from fangtype.workflow import TypeAnnotationWorkflow, _select_most_recent_variables


def _validation_result(type_str: str, is_valid: bool) -> TypeValidationResult:
    """Build a TypeValidationResult for mocked tests."""
    return TypeValidationResult(
        type_str=type_str,
        is_valid=is_valid,
        error_message=None if is_valid else "Validation failed",
    )


def _validate_bulk_reject_bogus(
    types_map: dict[object, str],
    _source: str,
    import_hints: object = None,
) -> dict[object, TypeValidationResult]:
    """Mocked validate_bulk side_effect: reject any type containing "Bogus", keyed per input map.

    Accepts and ignores import_hints, which the signature path now passes so a synthesised
    name is probed against a prelude that imports it.
    """
    return {
        key: _validation_result(type_str, "Bogus" not in type_str)
        for key, type_str in types_map.items()
    }


@pytest.fixture
def mock_settings() -> Settings:
    return Settings()


@pytest.fixture
def bare_inference_engine() -> MagicMock:
    mock = MagicMock()
    mock.infer_types = MagicMock()
    return mock


@pytest.fixture
def bare_insertion_engine() -> MagicMock:
    return MagicMock()


@pytest.fixture
def bare_removal_engine() -> MagicMock:
    return MagicMock()


@pytest.fixture
def bare_type_validator() -> MagicMock:
    mock = MagicMock()
    mock.validate_insertion = AsyncMock()
    mock.validate_bulk = AsyncMock()
    # Insert-path assignability gate (mypy_enabled default True) runs a full-file mypy pass;
    # default to "no diagnostics" so the gate is a no-op unless a test says otherwise.
    mock.validate_file_full = AsyncMock(return_value=[])
    return mock


@pytest.fixture
def workflow(
    bare_inference_engine: MagicMock,
    bare_insertion_engine: MagicMock,
    bare_removal_engine: MagicMock,
    bare_type_validator: MagicMock,
    mock_settings: Settings,
) -> TypeAnnotationWorkflow:
    return TypeAnnotationWorkflow(
        bare_inference_engine,
        bare_insertion_engine,
        bare_removal_engine,
        bare_type_validator,
        mock_settings,
        DocumentCache(),
    )


class TestInsertAllTypes:
    """Tests for insert_all_types."""

    async def test_insert_all_types_success(
        self,
        workflow: TypeAnnotationWorkflow,
        bare_inference_engine: MagicMock,
        bare_type_validator: MagicMock,
        bare_insertion_engine: MagicMock,
    ) -> None:
        """Test successful bulk insertion."""
        mock_inference_result = MagicMock()
        mock_inference_result.get_variable_insertion_candidates.return_value = {
            ("module", "x"): [(0, "int")]
        }
        mock_inference_result.get_function_insertions.return_value = {}
        mock_inference_result.get_attribute_insertions.return_value = {}
        bare_inference_engine.infer_types.return_value = mock_inference_result

        bare_type_validator.validate_bulk.return_value = {(0, "x"): _validation_result("int", True)}

        # Configure unified API mock
        from fangtype.insertion.types import InsertionResult

        mock_result = InsertionResult(
            success=True,
            modified_source="modified",
            inserted_count=1,
            error_message=None,
            details={},
            failed_targets=[],
        )
        bare_insertion_engine.insert.return_value = mock_result

        source, var_count, _func_count, msg = await workflow.insert_all_types("source", "file.py")

        assert var_count == 1
        assert source == "modified"
        assert "Inserted 1 type annotations" in msg

    async def test_insert_all_types_skips_validation_when_mypy_disabled(
        self,
        workflow: TypeAnnotationWorkflow,
        bare_inference_engine: MagicMock,
        bare_type_validator: MagicMock,
        bare_insertion_engine: MagicMock,
    ) -> None:
        """With mypy validation disabled, insert skips the validator; every variable passes."""

        mock_inference_result = MagicMock()
        mock_inference_result.get_variable_insertion_candidates.return_value = {
            ("module", "x"): [(0, "int")]
        }
        mock_inference_result.get_function_insertions.return_value = {}
        mock_inference_result.get_attribute_insertions.return_value = {}
        bare_inference_engine.infer_types.return_value = mock_inference_result

        from fangtype.insertion.types import InsertionResult

        bare_insertion_engine.insert.return_value = InsertionResult(
            success=True,
            modified_source="modified",
            inserted_count=1,
            error_message=None,
            details={},
            failed_targets=[],
        )

        _source, var_count, _func_count, _msg = await workflow.insert_all_types("source", "file.py")

        bare_type_validator.validate_bulk.assert_not_awaited()
        assert var_count == 1

    async def test_insert_all_types_no_types_found(
        self,
        workflow: TypeAnnotationWorkflow,
        bare_inference_engine: MagicMock,
        bare_type_validator: MagicMock,
        bare_insertion_engine: MagicMock,
    ) -> None:
        """Test when no types are inferred."""
        mock_inference_result = MagicMock()
        mock_inference_result.get_variable_insertion_candidates.return_value = {}
        mock_inference_result.get_function_insertions.return_value = {}
        mock_inference_result.get_attribute_insertions.return_value = {}
        bare_inference_engine.infer_types.return_value = mock_inference_result

        _source, vars_cnt, drop_reasons, msg = await workflow.insert_all_types("source", "file.py")

        assert vars_cnt == 0
        assert drop_reasons == {}
        assert "No types to insert" in msg
        bare_insertion_engine.insert_types_bulk.assert_not_called()

    async def test_insert_all_types_attribute_only_success_counts_as_inserted(
        self,
        workflow: TypeAnnotationWorkflow,
        bare_inference_engine: MagicMock,
        bare_type_validator: MagicMock,
        bare_insertion_engine: MagicMock,
    ) -> None:
        """Bug #3: an attribute-only file reports a non-zero count (inserted_count)."""
        source = "class C:\n    def __init__(self, width):\n        self.width = width\n"
        mock_inference_result = MagicMock()
        mock_inference_result.get_variable_insertion_candidates.return_value = {}
        mock_inference_result.get_function_insertions.return_value = {}
        mock_inference_result.get_attribute_insertions.return_value = {(3, "width"): "int"}
        bare_inference_engine.infer_types.return_value = mock_inference_result

        # side_effect (not return_value) so the mock responds to each call's own input map.
        bare_type_validator.validate_bulk.side_effect = _validate_bulk_reject_bogus

        from fangtype.insertion.types import InsertionResult

        annotated = "class C:\n    def __init__(self, width):\n        self.width: int = width\n"
        bare_insertion_engine.insert.return_value = InsertionResult(
            success=True,
            modified_source=annotated,
            inserted_count=1,
            error_message=None,
            details={},
            failed_targets=[],
        )

        result_source, count, _unused, msg = await workflow.insert_all_types(source, "file.py")

        assert count == 1
        assert result_source == annotated
        assert "Inserted 1" in msg

    async def test_insert_all_types_mixed_count_matches_message(
        self,
        workflow: TypeAnnotationWorkflow,
        bare_inference_engine: MagicMock,
        bare_type_validator: MagicMock,
        bare_insertion_engine: MagicMock,
    ) -> None:
        """Mixed var+attr file: the count and "Inserted N" message both reflect inserted_count."""
        source = "class C:\n    def __init__(self, width):\n        self.width = width\ny = 1\n"
        mock_inference_result = MagicMock()
        mock_inference_result.get_variable_insertion_candidates.return_value = {
            ("module", "y"): [(3, "int")]
        }
        mock_inference_result.get_function_insertions.return_value = {}
        mock_inference_result.get_attribute_insertions.return_value = {(2, "width"): "int"}
        bare_inference_engine.infer_types.return_value = mock_inference_result

        # side_effect (not return_value) so each validate_bulk call responds to its own input map.
        bare_type_validator.validate_bulk.side_effect = _validate_bulk_reject_bogus

        from fangtype.insertion.types import InsertionResult

        bare_insertion_engine.insert.return_value = InsertionResult(
            success=True,
            modified_source="modified",
            inserted_count=2,
            error_message=None,
            details={},
            failed_targets=[],
        )

        _source, count, _unused, msg = await workflow.insert_all_types(source, "file.py")

        assert count == 2
        assert f"Inserted {count} type annotations" == msg

    async def test_insert_all_types_partial_engine_result_reports_positive_count(
        self,
        workflow: TypeAnnotationWorkflow,
        bare_inference_engine: MagicMock,
        bare_type_validator: MagicMock,
        bare_insertion_engine: MagicMock,
    ) -> None:
        """A partial InsertionResult yields a positive count (bulk gate is inserted_count==0)."""
        mock_inference_result = MagicMock()
        mock_inference_result.get_variable_insertion_candidates.return_value = {
            ("module", "x"): [(0, "int")],
            ("module", "y"): [(1, "int")],
        }
        mock_inference_result.get_function_insertions.return_value = {}
        mock_inference_result.get_attribute_insertions.return_value = {}
        bare_inference_engine.infer_types.return_value = mock_inference_result

        bare_type_validator.validate_bulk.return_value = {
            (0, "x"): _validation_result("int", True),
            (1, "y"): _validation_result("int", True),
        }

        from fangtype.insertion import create_variable_target
        from fangtype.insertion.types import InsertionResult

        # Engine planned "x" but skipped "y" -- a partial success, not all-or-nothing error_result.
        failed_target = create_variable_target("y", "int", 2)
        bare_insertion_engine.insert.return_value = InsertionResult(
            success=True,
            modified_source="modified",
            inserted_count=1,
            error_message=None,
            details={"skipped_count": 1},
            failed_targets=[failed_target],
        )

        source, var_count, _func_count, msg = await workflow.insert_all_types("source", "file.py")

        assert var_count == 1
        assert source == "modified"
        assert "Inserted 1 type annotations" in msg


class TestVariableDropReasons:
    """Bucketing surfaced variables into selected vs all_mypy_invalid (folded into insert path)."""

    def test_counts_selected_and_all_invalid(self) -> None:
        candidates = {
            ("module", "x"): [(2, "str"), (0, "int")],  # earlier int valid -> selected
            ("module", "y"): [(3, "Bogus")],  # only binding invalid -> all_mypy_invalid
        }
        selected = {(0, "x"): _validation_result("int", True)}

        assert workflow_module._bucket_variable_drop_reasons(candidates, selected) == {
            "selected": 1,
            "all_mypy_invalid": 1,
        }


class TestSelectMostRecentVariables:
    """Variable selection: the most recent binding per name wins, and nothing is judged here."""

    def test_picks_the_most_recent_binding(self) -> None:
        """Candidates arrive most-recent-first, so the first entry for a name is taken."""
        candidates = {("module", "x"): [(2, "str"), (0, "int")]}
        assert _select_most_recent_variables(candidates) == {
            (2, "x"): _validation_result("str", True)
        }

    def test_same_name_distinct_scopes_kept_separate(self) -> None:
        """A module ``x`` and a function ``x`` are independent, so both survive."""
        candidates = {("module", "x"): [(5, "int")], ("func:f", "x"): [(10, "str")]}
        assert _select_most_recent_variables(candidates) == {
            (5, "x"): _validation_result("int", True),
            (10, "x"): _validation_result("str", True),
        }

    def test_empty_candidates_returns_empty(self) -> None:
        """No candidates in, nothing out."""
        assert _select_most_recent_variables({}) == {}

    def test_every_candidate_is_reported_valid(self) -> None:
        """Selection judges nothing. The assignability gate is what rejects a type."""
        candidates = {("module", "x"): [(0, "Nonsense")]}
        selected = _select_most_recent_variables(candidates)
        assert selected[(0, "x")].is_valid is True


class TestBuildTargetsSelfAttribute:
    """Instance-attribute (``self.x``) targets from ``_build_targets``."""

    def test_bare_attribute_key_becomes_self_attribute_target(
        self, workflow: TypeAnnotationWorkflow
    ) -> None:
        """A bare (no-dot) attribute key yields a dotted self.w target at the assignment line."""
        source = "class C:\n    def __init__(self, w):\n        self.w = w\n"

        targets = workflow._build_targets(
            None,  # validated_vars (mypy disabled)
            {},  # variable_insertions
            {},  # function_insertions
            {(3, "w"): "int"},  # attribute_insertions: bare key = self.w at line 3
            source,
        )

        attr_targets = [t for t in targets if t.target_type == TargetType.ATTRIBUTE_ACCESS]
        assert len(attr_targets) == 1
        assert attr_targets[0].name == "self.w"
        assert attr_targets[0].type_annotation == "int"
        assert attr_targets[0].location.line == 3

    def test_dotted_non_self_attribute_key_unchanged(
        self, workflow: TypeAnnotationWorkflow
    ) -> None:
        """A dotted ``obj.x`` key keeps its existing behavior (regression guard)."""
        source = "obj = Obj()\nobj.x = 5\n"

        targets = workflow._build_targets(
            None,
            {},
            {},
            {(2, "obj.x"): "int"},
            source,
        )

        attr_targets = [t for t in targets if t.target_type == TargetType.ATTRIBUTE_ACCESS]
        assert len(attr_targets) == 1
        assert attr_targets[0].name == "obj.x"


class TestPreviewInsertions:
    """Tests for preview_insertions."""

    async def test_preview_insertions_success(
        self,
        workflow: TypeAnnotationWorkflow,
        bare_inference_engine: MagicMock,
        bare_type_validator: MagicMock,
        bare_insertion_engine: MagicMock,
    ) -> None:
        """Test successful preview."""
        mock_inference_result = MagicMock()
        mock_inference_result.get_variable_insertions.return_value = {(0, "x"): "int"}
        mock_inference_result.get_function_insertions.return_value = {}
        mock_inference_result.get_attribute_insertions.return_value = {}
        bare_inference_engine.infer_types.return_value = mock_inference_result

        bare_type_validator.validate_bulk.return_value = {(0, "x"): _validation_result("int", True)}

        bare_insertion_engine.preview_insertions.return_value = {
            "success": True,
            "total_plans": 1,
            "plan_details": [{"target": "x", "type": "int"}],
        }

        preview = await workflow.preview_insertions("source")
        assert preview == {"will_insert": [{"variable": "x", "type": "int"}], "total_changes": 1}

    async def test_preview_insertions_skips_validation_when_mypy_disabled(
        self,
        workflow: TypeAnnotationWorkflow,
        bare_inference_engine: MagicMock,
        bare_type_validator: MagicMock,
        bare_insertion_engine: MagicMock,
    ) -> None:
        """preview_insertions also skips mypy validation when disabled (benchmark scope tree)."""

        mock_inference_result = MagicMock()
        mock_inference_result.get_variable_insertions.return_value = {(0, "x"): "int"}
        mock_inference_result.get_function_insertions.return_value = {}
        mock_inference_result.get_attribute_insertions.return_value = {}
        bare_inference_engine.infer_types.return_value = mock_inference_result

        bare_insertion_engine.preview_insertions.return_value = {
            "success": True,
            "total_plans": 1,
            "plan_details": [{"target": "x", "type": "int"}],
        }

        preview = await workflow.preview_insertions("source")

        bare_type_validator.validate_bulk.assert_not_awaited()
        assert preview == {"will_insert": [{"variable": "x", "type": "int"}], "total_changes": 1}

    async def test_preview_insertions_requests_per_binding_variables(
        self,
        workflow: TypeAnnotationWorkflow,
        bare_inference_engine: MagicMock,
    ) -> None:
        """Preview reports every assignment site, so it requests per-binding variables."""
        mock_inference_result = MagicMock()
        mock_inference_result.get_variable_insertions.return_value = {}
        mock_inference_result.get_function_insertions.return_value = {}
        mock_inference_result.get_attribute_insertions.return_value = {}
        bare_inference_engine.infer_types.return_value = mock_inference_result

        await workflow.preview_insertions("source")

        mock_inference_result.get_variable_insertions.assert_called_once_with(per_binding=True)

    async def test_insert_all_types_uses_candidate_enumerator_not_per_binding(
        self,
        workflow: TypeAnnotationWorkflow,
        bare_inference_engine: MagicMock,
    ) -> None:
        """Insert uses get_variable_insertion_candidates (one per name), never per_binding."""
        mock_inference_result = MagicMock()
        mock_inference_result.get_variable_insertion_candidates.return_value = {}
        mock_inference_result.get_function_insertions.return_value = {}
        mock_inference_result.get_attribute_insertions.return_value = {}
        bare_inference_engine.infer_types.return_value = mock_inference_result

        await workflow.insert_all_types("source", "file.py")

        mock_inference_result.get_variable_insertion_candidates.assert_called_once_with()
        mock_inference_result.get_variable_insertions.assert_not_called()

    async def test_preview_insertions_no_types(
        self, workflow: TypeAnnotationWorkflow, bare_inference_engine: MagicMock
    ) -> None:
        """Test preview when no types inferred."""
        mock_inference_result = MagicMock()
        mock_inference_result.get_variable_insertions.return_value = {}
        mock_inference_result.get_function_insertions.return_value = {}
        mock_inference_result.get_attribute_insertions.return_value = {}
        bare_inference_engine.infer_types.return_value = mock_inference_result

        preview = await workflow.preview_insertions("source")
        assert preview == {"will_insert": [], "total_changes": 0}


class TestTypeCollection:
    """The inlay-path type collection entry point."""

    async def test_collect_types_returns_the_inference_result_without_running_mypy(
        self,
        workflow: TypeAnnotationWorkflow,
        bare_type_validator: MagicMock,
    ) -> None:
        """The hint path infers and returns. No mypy runs before a hint is drawn."""
        mock_inference_result = MagicMock()
        mock_infer = MagicMock(return_value=mock_inference_result)
        object.__setattr__(workflow._inference_engine, "infer_types", mock_infer)

        inference_result = await workflow.collect_types("source", "file.py")

        assert inference_result is mock_inference_result
        mock_infer.assert_called_once_with(
            "source",
            path="file.py",
            project_root=None,
            cancel_token=None,
        )
        bare_type_validator.validate_file_full.assert_not_awaited()


_F_PARAMS: FunctionInsertionInfo = {
    "name": "f",
    "params": {"a": "int", "b": "str"},
    "return_type": None,
}
_F_NAME: FunctionInsertionInfo = {"name": "f", "params": {}, "return_type": None}
_F_ONE_PARAM: FunctionInsertionInfo = {"name": "f", "params": {"a": "int"}, "return_type": None}


class TestRestrictToTarget:
    """Tests for the _restrict_to_target selector (compute one, not all)."""

    @pytest.mark.parametrize(
        ("target", "variables", "functions", "attributes", "expected"),
        [
            pytest.param(
                ("x", 0),
                {(0, "x"): "int", (5, "y"): "str"},
                {},
                {},
                ({(0, "x"): "int"}, {}, {}),
                id="variable_exact_line",
            ),
            # name matches on line 0; cursor is on a usage at line 4 -> nearest <= 4
            pytest.param(
                ("x", 4),
                {(0, "x"): "int", (9, "x"): "bool"},
                {},
                {},
                ({(0, "x"): "int"}, {}, {}),
                id="variable_usage_picks_nearest_preceding",
            ),
            pytest.param(
                ("nope", 0),
                {(0, "x"): "int"},
                {},
                {},
                ({}, {}, {}),
                id="variable_no_match_is_empty",
            ),
            pytest.param(
                ("self.width", 2),
                {},
                {},
                {(3, "self.width"): "int", (4, "self.height"): "int"},
                ({}, {}, {(3, "self.width"): "int"}),
                id="attribute_full_name_match",
            ),
            pytest.param(
                ("a", 0),
                {},
                {(0, "f"): _F_PARAMS},
                {},
                ({}, {(0, "f"): _F_PARAMS}, {}),
                id="function_kept_when_param_matches",
            ),
            pytest.param(
                ("f", 0),
                {},
                {(0, "f"): _F_NAME},
                {},
                ({}, {(0, "f"): _F_NAME}, {}),
                id="function_kept_when_name_matches",
            ),
            pytest.param(
                ("z", 0),
                {},
                {(0, "f"): _F_ONE_PARAM},
                {},
                ({}, {}, {}),
                id="function_dropped_when_unrelated",
            ),
        ],
    )
    def test_restrict_to_target(self, target, variables, functions, attributes, expected) -> None:
        assert (
            workflow_module._restrict_to_target(target, variables, functions, attributes)
            == expected
        )


class TestDocumentCacheReuse:
    """_infer_cached serves the DocumentCache when the document is unchanged."""

    @staticmethod
    def _complete(tag: str) -> MagicMock:
        result = MagicMock()
        result.is_complete = True
        result.tag = tag
        return result

    URI = "file:///f.py"

    async def test_same_uri_version_infers_once(self, workflow: TypeAnnotationWorkflow) -> None:
        workflow._inference_engine.infer_types.return_value = self._complete("r")

        r1 = await workflow._infer_cached("x = 1\n", "f.py", self.URI, 1, None)
        r2 = await workflow._infer_cached("x = 1\n", "f.py", self.URI, 1, None)

        assert r1 is r2
        workflow._inference_engine.infer_types.assert_called_once()

    async def test_uri_none_bypasses_cache(self, workflow: TypeAnnotationWorkflow) -> None:
        workflow._inference_engine.infer_types.side_effect = [
            self._complete("a"),
            self._complete("b"),
        ]

        await workflow._infer_cached("x = 1\n", "f.py", None, 1, None)
        await workflow._infer_cached("x = 1\n", "f.py", None, 1, None)

        assert workflow._inference_engine.infer_types.call_count == 2

    async def test_cancelled_result_not_cached(self, workflow: TypeAnnotationWorkflow) -> None:
        from fangtype.cancellation import CancellationToken

        token = CancellationToken()
        token.cancel()
        workflow._inference_engine.infer_types.side_effect = [
            self._complete("a"),
            self._complete("b"),
        ]

        await workflow._infer_cached("x = 1\n", "f.py", self.URI, 1, token)
        # A cancelled (partial) result is never cached, so the next call recomputes.
        await workflow._infer_cached("x = 1\n", "f.py", self.URI, 1, None)

        assert workflow._inference_engine.infer_types.call_count == 2

    async def test_incomplete_fallback_not_cached(self, workflow: TypeAnnotationWorkflow) -> None:
        incomplete = MagicMock()
        incomplete.is_complete = False
        workflow._inference_engine.infer_types.side_effect = [incomplete, self._complete("full")]

        await workflow._infer_cached("x = 1\n", "f.py", self.URI, 1, None)
        second = await workflow._infer_cached("x = 1\n", "f.py", self.URI, 1, None)

        assert workflow._inference_engine.infer_types.call_count == 2
        assert second.is_complete is True


class TestAnnotateAtPosition:
    """Tests for annotate_at_position (single cursor target, no Jedi)."""

    @staticmethod
    def _ok_result(modified: str) -> "object":
        from fangtype.insertion.types import InsertionResult

        return InsertionResult(
            success=True,
            modified_source=modified,
            inserted_count=1,
            error_message=None,
            details={},
            failed_targets=[],
        )

    async def test_success_simple_variable(
        self, workflow: TypeAnnotationWorkflow, bare_insertion_engine: MagicMock
    ) -> None:
        from fangtype.insertion import create_variable_target

        target = create_variable_target("x", "int", 1)
        mock_prepare = AsyncMock(return_value=([target], 1, 0, None, {}))
        object.__setattr__(workflow, "_prepare_insertion_targets", mock_prepare)
        bare_insertion_engine.insert.return_value = self._ok_result("x: int = 1\n")

        result = await workflow.annotate_at_position("x = 1\n", None, 0, 0)

        assert result["insertion_success"] is True
        assert result["inferred_type"] == "int"
        assert result["name"] == "x"
        assert result["modified_source"] == "x: int = 1\n"
        assert result["message"] == "Inserted type annotation: x: int"
        # scoped to the one target
        assert mock_prepare.call_args.kwargs["only"] == ("x", 0)
        bare_insertion_engine.insert.assert_called_once_with([target], "x = 1\n")

    async def test_cursor_on_earlier_binding_annotates_that_binding(
        self,
        workflow: TypeAnnotationWorkflow,
        bare_inference_engine: MagicMock,
        bare_insertion_engine: MagicMock,
    ) -> None:
        """Cursor on the first of two ``x`` bindings annotates line 1 as int, not the later str.

        Drives the real _prepare_insertion_targets: collapsing to the last binding silently
        annotated the *wrong line* (reported as success).
        """
        import ast

        from fangtype.analysis import Scope, ScopeType, TypeInfo, TypeSource
        from fangtype.analysis.types import ScopeTree
        from fangtype.inference.inference_result import InferenceResult

        source = 'x = 5\nprint(x)\nx = "hello"\n'
        module = Scope(
            scope_id="module",
            scope_type=ScopeType.MODULE,
            name="module",
            ast_node=ast.parse(source),
        )
        module.add_variable("x", TypeInfo(type_str="int", source=TypeSource.LITERAL, line=0, col=0))
        module.add_variable("x", TypeInfo(type_str="str", source=TypeSource.LITERAL, line=2, col=0))
        scope_tree = ScopeTree(root=module)
        scope_tree.add_scope(module)
        bare_inference_engine.infer_types.return_value = InferenceResult(
            scope_tree=scope_tree, source=source
        )
        bare_insertion_engine.insert.return_value = self._ok_result("x: int = 5\n")

        result = await workflow.annotate_at_position(source, None, 0, 0)

        assert result["insertion_success"] is True
        assert result["inferred_type"] == "int"
        (targets, _src) = bare_insertion_engine.insert.call_args.args
        assert [(t.name, t.type_annotation, t.location.line) for t in targets] == [("x", "int", 1)]

    async def test_success_parameter(
        self, workflow: TypeAnnotationWorkflow, bare_insertion_engine: MagicMock
    ) -> None:
        from fangtype.insertion import CodeLocation, InsertionTarget, TargetType

        target = InsertionTarget(
            target_type=TargetType.FUNCTION_PARAMETER,
            location=CodeLocation(line=1, column=0),
            type_annotation="int",
            name="a",
        )
        object.__setattr__(
            workflow,
            "_prepare_insertion_targets",
            AsyncMock(return_value=([target], 0, 1, None, {})),
        )
        bare_insertion_engine.insert.return_value = self._ok_result("def f(a: int):\n    pass\n")

        result = await workflow.annotate_at_position("def f(a):\n    pass\n", None, 0, 6)

        assert result["insertion_success"] is True
        assert result["name"] == "a"
        assert result["inferred_type"] == "int"
        assert result["message"] == "Inserted type annotation: a: int"

    async def test_success_attribute(
        self, workflow: TypeAnnotationWorkflow, bare_insertion_engine: MagicMock
    ) -> None:
        from fangtype.insertion import CodeLocation, InsertionTarget, TargetType

        source = "class C:\n    def __init__(self):\n        self.flag = True\n"
        target = InsertionTarget(
            target_type=TargetType.ATTRIBUTE_ACCESS,
            location=CodeLocation(line=3, column=0),
            type_annotation="bool",
            name="self.flag",
        )
        object.__setattr__(
            workflow,
            "_prepare_insertion_targets",
            AsyncMock(return_value=([target], 0, 0, None, {})),
        )
        bare_insertion_engine.insert.return_value = self._ok_result("modified")

        result = await workflow.annotate_at_position(source, None, 2, 14)  # cursor on "flag"

        assert result["insertion_success"] is True
        assert result["name"] == "self.flag"
        assert result["message"] == "Inserted type annotation: self.flag: bool"

    async def test_failure_nothing_at_cursor_short_circuits(
        self, workflow: TypeAnnotationWorkflow
    ) -> None:
        mock_prepare = AsyncMock()
        object.__setattr__(workflow, "_prepare_insertion_targets", mock_prepare)

        result = await workflow.annotate_at_position("x = 1\n", None, 0, 3)  # whitespace

        assert result["insertion_success"] is False
        error_message = result["error_message"]
        assert isinstance(error_message, str)
        assert "No variable or expression" in error_message
        mock_prepare.assert_not_awaited()

    async def test_failure_no_matching_target(
        self, workflow: TypeAnnotationWorkflow, bare_insertion_engine: MagicMock
    ) -> None:
        object.__setattr__(
            workflow, "_prepare_insertion_targets", AsyncMock(return_value=([], 0, 0, None, {}))
        )

        result = await workflow.annotate_at_position("x = 1\n", None, 0, 0)

        assert result["insertion_success"] is False
        bare_insertion_engine.insert.assert_not_called()

    async def test_failure_early_message(self, workflow: TypeAnnotationWorkflow) -> None:
        object.__setattr__(
            workflow,
            "_prepare_insertion_targets",
            AsyncMock(
                return_value=(
                    [],
                    0,
                    0,
                    "No valid types to insert (all types failed validation)",
                    {},
                )
            ),
        )

        result = await workflow.annotate_at_position("x = 1\n", None, 0, 0)

        assert result["insertion_success"] is False
        error_message = result["error_message"]
        assert isinstance(error_message, str)
        assert "failed validation" in error_message

    async def test_cancellation_propagates_and_threads_token(
        self, workflow: TypeAnnotationWorkflow
    ) -> None:
        import asyncio

        from fangtype.cancellation import CancellationToken

        token = CancellationToken()
        mock_prepare = AsyncMock(side_effect=asyncio.CancelledError)
        object.__setattr__(workflow, "_prepare_insertion_targets", mock_prepare)

        with pytest.raises(asyncio.CancelledError):
            await workflow.annotate_at_position("x = 1\n", None, 0, 0, cancel_token=token)

        assert mock_prepare.call_args.kwargs["cancel_token"] is token


class TestAnnotateAtPositionSelfAttributeCursor:
    """Bug #2 regression: cursor on self.x through the REAL pipeline (no _prepare mocking)."""

    async def test_self_attribute_cursor_inserts_annotation(
        self,
        workflow: TypeAnnotationWorkflow,
        bare_inference_engine: MagicMock,
        bare_insertion_engine: MagicMock,
    ) -> None:
        """Cursor on width in self.width = width succeeds end-to-end (bare key vs dotted name)."""
        # Skip the mypy round-trip -- this test is about the restriction filter, not validation.

        source = "class C:\n    def __init__(self, width):\n        self.width = width\n"

        mock_inference_result = MagicMock()
        mock_inference_result.get_variable_insertions.return_value = {}
        mock_inference_result.get_function_insertions.return_value = {}
        mock_inference_result.get_attribute_insertions.return_value = {(3, "width"): "int"}
        bare_inference_engine.infer_types.return_value = mock_inference_result

        from fangtype.insertion.types import InsertionResult

        bare_insertion_engine.insert.return_value = InsertionResult(
            success=True,
            modified_source=(
                "class C:\n    def __init__(self, width):\n        self.width: int = width\n"
            ),
            inserted_count=1,
            error_message=None,
            details={},
            failed_targets=[],
        )

        result = await workflow.annotate_at_position(source, "file.py", line=2, character=13)

        assert result["insertion_success"] is True
        assert result["inferred_type"] == "int"


class TestInsertPathAssignabilityGate:
    """M31: insert path runs a REAL mypy assignability pass over the modified file.

    Wrong-but-well-formed types (Jedi infers ``int`` for a ``str``) pass the bare-annotation
    pre-pass but must be dropped by the full-file gate; a correct sibling must survive.
    Drives real InsertionEngine + real MypyTypeValidator (not mocks) so line-mapping is exercised.
    """

    @staticmethod
    def _workflow_real(
        candidates: dict[tuple[str, str], list[tuple[int, str]]], settings: Settings
    ):
        from fangtype.insertion import InsertionEngine
        from fangtype.removal import RemovalEngine
        from fangtype.validation.mypy_validator import MypyTypeValidator

        inference_result = MagicMock()
        inference_result.get_variable_insertion_candidates.return_value = candidates
        inference_result.get_variable_insertions.return_value = {}
        inference_result.get_function_insertions.return_value = {}
        inference_result.get_attribute_insertions.return_value = {}

        inference = MagicMock()
        inference.infer_types.return_value = inference_result

        return TypeAnnotationWorkflow(
            inference,
            InsertionEngine(),
            RemovalEngine(),
            MypyTypeValidator(settings),
            settings,
            DocumentCache(),
        )

    async def test_wrong_type_dropped_correct_survives(self) -> None:
        """x="s" wrongly inferred int is dropped; y=3 correctly int survives (gate ON, default)."""
        settings = Settings()  # mypy_enabled True
        source = 'x = "s"\ny = 3\n'
        candidates = {("module", "x"): [(0, "int")], ("module", "y"): [(1, "int")]}
        workflow = self._workflow_real(candidates, settings)

        modified, _count, _f, _msg = await workflow.insert_all_types(source, "file.py")

        assert "y: int = 3" in modified  # correct type survives
        assert "x: int" not in modified  # wrong type dropped
        assert 'x = "s"' in modified  # x left untouched

    async def test_interdependent_survivor_re_dropped_to_fixpoint(self) -> None:
        """x="s" (wrongly int) is dropped; y=x is int ONLY while x:int present, so it must go too.

        Trial (x:int="s" + y:int=x) → mypy flags only line 1 (x); a single-pass gate would keep
        y:int=x, but re-inserting y WITHOUT x's annotation makes y revert to str → y:int=x is now
        a fresh [assignment] error. The fixpoint re-gate must catch and drop y as well.
        """
        settings = Settings()  # mypy_enabled True
        source = 'x = "s"\ny = x\n'
        candidates = {("module", "x"): [(0, "int")], ("module", "y"): [(1, "int")]}
        workflow = self._workflow_real(candidates, settings)

        modified, _count, _f, _msg = await workflow.insert_all_types(source, "file.py")

        assert "x: int" not in modified  # root wrong type dropped
        assert "y: int" not in modified  # dependent survivor re-dropped at fixpoint
        assert 'x = "s"' in modified  # both left untouched
        assert "y = x" in modified

    async def test_gate_off_writes_even_the_wrong_type(self) -> None:
        """With mypy_enabled False the pre-change behavior stands: the wrong int is written."""
        settings = Settings()
        settings.mypy_enabled = False
        source = 'x = "s"\ny = 3\n'
        candidates = {("module", "x"): [(0, "int")], ("module", "y"): [(1, "int")]}
        workflow = self._workflow_real(candidates, settings)

        modified, _count, _f, _msg = await workflow.insert_all_types(source, "file.py")

        assert "x: int" in modified  # ungated: the wrong type IS written
        assert "y: int = 3" in modified


class TestGateAttributesInsertedDeclarations:
    """The gate has to see errors landing on a declaration it wrote, not just on paired lines.

    A DECLARATION target adds a line that has no counterpart in the original, so the
    modified-to-original map has to carry it or every diagnostic on it is discarded before the
    intersection with the target lines ever happens.
    """

    def test_inserted_line_maps_to_the_statement_it_precedes(self) -> None:
        from fangtype.workflow import _map_modified_to_original

        source = "def f(seq):\n    for total in seq:\n        pass\n"
        modified = "def f(seq):\n    total: int\n    for total in seq:\n        pass\n"

        mapping = _map_modified_to_original(source, modified)

        # The inserted declaration is modified line 2 and stands above original line 2.
        assert mapping[2] == 2
        assert mapping[3] == 2
        assert mapping[4] == 3

    def test_no_redef_on_an_inserted_declaration_flags_its_target(self) -> None:
        from fangtype.insertion.types import CodeLocation, InsertionTarget, TargetType
        from fangtype.validation.mypy_diagnostic import MypyDiagnostic
        from fangtype.workflow import _flagged_target_lines

        source = "def f(seq):\n    for total in seq:\n        pass\n"
        modified = "def f(seq):\n    total: int\n    for total in seq:\n        pass\n"
        target = InsertionTarget(
            target_type=TargetType.ITERATION_VARIABLE,
            location=CodeLocation(line=2, column=0),
            type_annotation="int",
            name="total",
        )
        diagnostics = [
            MypyDiagnostic(
                line=2,
                column=4,
                message='Name "total" already defined on line 1',
                error_code="no-redef",
                severity="error",
            )
        ]

        assert _flagged_target_lines([target], source, modified, diagnostics) == {2}

    def test_name_defined_is_acted_on(self) -> None:
        """An annotation naming something the file never imports breaks it at import time."""
        from fangtype.workflow import _INCOMPATIBLE_CODES

        assert {"no-redef", "name-defined", "return-value"} <= _INCOMPATIBLE_CODES
