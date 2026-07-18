"""Chained assigns route to VARIABLE_COMPLEX; multi-target guard drops no target."""

from fangtype.insertion import (
    CodeLocation,
    InsertionEngine,
    InsertionTarget,
    TargetType,
)
from fangtype.insertion.target_factory import (
    build_source_index,
    create_variable_target,
    find_assignment_target_indexed,
)

_CHAINED_SRC = "a = b = c = 10\n"


class TestBuildSourceIndexClassifiesChainedAssignment:
    """`build_source_index` must route every bare-name target of a chain to COMPLEX."""

    def test_all_targets_classified_variable_complex(self) -> None:
        index = build_source_index(_CHAINED_SRC)
        assert index is not None

        for name in ("a", "b", "c"):
            candidates = index.assignment_candidates_by_name[name]
            assert len(candidates) == 1
            assert candidates[0].target_type == TargetType.VARIABLE_COMPLEX
            assert candidates[0].line_1_based == 1

    def test_single_target_assignment_unaffected(self) -> None:
        """Non-chained assigns keep their existing classification (no regression)."""
        index = build_source_index("x = 1\n")
        assert index is not None
        candidates = index.assignment_candidates_by_name["x"]
        assert candidates[0].target_type == TargetType.VARIABLE_SIMPLE


class TestChainedAssignmentInsertionEndToEnd:
    """Inserting annotations on a chained assignment must not delete any target."""

    def test_all_targets_preserved_and_output_compiles(self) -> None:
        index = build_source_index(_CHAINED_SRC)
        assert index is not None

        targets: list[InsertionTarget] = []
        for name in ("a", "b", "c"):
            resolved = find_assignment_target_indexed(index, name, 0)
            assert resolved is not None
            assert resolved.target_type == TargetType.VARIABLE_COMPLEX
            targets.append(
                create_variable_target(
                    name, "int", resolved.line_1_based, target_type=resolved.target_type
                )
            )

        result = InsertionEngine().insert(targets, _CHAINED_SRC)

        assert result.success
        # Must never raise: proves the output is not corrupted.
        compile(result.modified_source, "<test>", "exec")

        # The chained assignment itself is untouched; declarations are added above it.
        assert "a = b = c = 10" in result.modified_source
        assert "a: int" in result.modified_source
        assert "b: int" in result.modified_source
        assert "c: int" in result.modified_source


class TestTransformerGuardAgainstMultiTargetInPlace:
    """Even a stray IN_PLACE plan on a multi-target assign must not corrupt the file."""

    def test_in_place_plan_on_chained_assignment_fails_safely(self) -> None:
        # In-place VARIABLE_SIMPLE target on the chain proves the transformer guard holds.
        target = InsertionTarget(
            target_type=TargetType.VARIABLE_SIMPLE,
            location=CodeLocation(line=1, column=0),
            type_annotation="int",
            name="a",
        )

        result = InsertionEngine().insert([target], _CHAINED_SRC)

        assert result.success
        assert result.inserted_count == 0
        # Nothing changed: no dropped targets, no partial annotation.
        assert result.modified_source == _CHAINED_SRC

        failed_plans = result.details["failed_plans"]
        assert isinstance(failed_plans, list)
        assert len(failed_plans) == 1
        assert failed_plans[0]["target"] == "a"


class TestMixedTargetChainNeverCorrupts:
    """Chain mixing a bare name and non-annotatable sibling (`a = self.b = 10`) drops no target."""

    _MIXED_SRC = "class C:\n    def m(self) -> None:\n        a = self.b = 10\n"

    def test_in_place_plan_on_mixed_chain_leaves_source_intact(self) -> None:
        # In-place plan on the bare-name arm: the guard must refuse it, not partially rewrite.
        target = InsertionTarget(
            target_type=TargetType.VARIABLE_SIMPLE,
            location=CodeLocation(line=3, column=0),
            type_annotation="int",
            name="a",
        )

        result = InsertionEngine().insert([target], self._MIXED_SRC)

        assert result.success
        assert result.inserted_count == 0
        assert result.modified_source == self._MIXED_SRC
        # Output still compiles and the chained statement is intact.
        compile(result.modified_source, "<test>", "exec")
        assert "a = self.b = 10" in result.modified_source
