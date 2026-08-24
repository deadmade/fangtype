"""Callable-contract propagation: parser/alignment pieces plus Jedi (params-only, fill-only)."""

from __future__ import annotations

import ast
import inspect
import textwrap
from unittest.mock import MagicMock

import jedi
import pytest

import fangtype.inference.contract_propagation as contract_propagation
from fangtype.analysis.types import ScopeTree, TypeSource
from fangtype.inference.contract_propagation import (
    CallableContract,
    align_contract,
    apply_contract_propagation,
    merge_contracts,
    parse_callable_contract,
)
from fangtype.inference.jedi.engine import JediInferenceEngine
from fangtype.inference.jedi.scope_builder import build_scope_tree
from fangtype.utils.settings import Settings


def _func(src: str) -> ast.FunctionDef:
    node = ast.parse(src).body[0]
    assert isinstance(node, ast.FunctionDef)
    return node


def _scope(result, qualified_name: str):
    scope = result.scope_tree.get_function_scope_by_qualified_name(qualified_name)
    assert scope is not None, f"scope {qualified_name} not found"
    return scope


class TestParseCallableContract:
    @pytest.mark.parametrize(
        ("annotation", "expected"),
        [
            pytest.param(
                "Callable[[FunctionContext], Type] | None",
                CallableContract(params=["FunctionContext"], ret="Type"),
                id="single_param_with_none_arm",
            ),
            pytest.param(
                "Callable[[ClassDefContext], None] | None",
                CallableContract(params=["ClassDefContext"], ret="None"),
                id="none_return_contract",
            ),
            pytest.param(
                "Callable[[MethodSigContext], FunctionLike]",
                CallableContract(params=["MethodSigContext"], ret="FunctionLike"),
                id="without_none_arm",
            ),
            pytest.param(
                "Callable[[A, B], R]",
                CallableContract(params=["A", "B"], ret="R"),
                id="multiple_params",
            ),
            pytest.param(
                "Callable[[list[int]], dict[str, int]]",
                CallableContract(params=["list[int]"], ret="dict[str, int]"),
                id="nested_generic_params_and_return",
            ),
            pytest.param(
                "Callable[..., int]",
                CallableContract(params=None, ret="int"),
                id="ellipsis_params_yield_none_params",
            ),
            pytest.param(
                "typing.Callable[[X], Y] | None",
                CallableContract(params=["X"], ret="Y"),
                id="qualified_callable_name",
            ),
            pytest.param("Callable", None, id="bare_callable"),
            pytest.param("Callable | None", None, id="bare_callable_with_none_arm"),
            pytest.param("int", None, id="non_callable_scalar"),
            pytest.param("list[int]", None, id="non_callable_generic"),
            pytest.param(None, None, id="none_input"),
            pytest.param("", None, id="empty_input"),
            # `Callable[...] | int` is not a single Callable contract -> ambiguous.
            pytest.param("Callable[[X], Y] | int", None, id="callable_unioned_with_other_type"),
        ],
    )
    def test_parse(self, annotation: str | None, expected: CallableContract | None) -> None:
        assert parse_callable_contract(annotation) == expected


class TestBindContract:
    """L11: a contract naming a base typevar must be substituted or dropped, never leaked."""

    def test_substitutes_single_arg_typevar(self) -> None:
        contract = CallableContract(params=["T"], ret="T")
        bound = contract_propagation._bind_contract(contract, ["int"])
        assert bound == CallableContract(params=["int"], ret="int")

    def test_drops_contract_with_unresolved_param_typevar(self) -> None:
        contract = CallableContract(params=["T"], ret="None")
        assert contract_propagation._bind_contract(contract, []) is None

    def test_drops_contract_with_unresolved_return_typevar(self) -> None:
        contract = CallableContract(params=["int"], ret="T")
        assert contract_propagation._bind_contract(contract, []) is None

    def test_keeps_plain_contract_untouched(self) -> None:
        contract = CallableContract(params=["FunctionContext"], ret="Type")
        assert contract_propagation._bind_contract(contract, []) == contract


class TestAlignContract:
    def test_fills_positional_param_and_return(self) -> None:
        func = _func("def cb(ctx):\n    return 1\n")
        c = CallableContract(params=["FunctionContext"], ret="Type")
        assert align_contract(func, c) == {"ctx": "FunctionContext", "return": "Type"}

    def test_skips_already_annotated_param(self) -> None:
        func = _func("def cb(ctx: Something):\n    return 1\n")
        c = CallableContract(params=["FunctionContext"], ret="Type")
        # ctx already annotated -> fill-only leaves it; return still filled.
        assert align_contract(func, c) == {"return": "Type"}

    def test_skips_return_when_already_annotated(self) -> None:
        func = _func("def cb(ctx) -> X:\n    return 1\n")
        c = CallableContract(params=["FunctionContext"], ret="Type")
        assert align_contract(func, c) == {"ctx": "FunctionContext"}

    def test_skips_leading_self(self) -> None:
        func = _func("def cb(self, ctx):\n    return 1\n")
        c = CallableContract(params=["FunctionContext"], ret="Type")
        assert align_contract(func, c) == {"ctx": "FunctionContext", "return": "Type"}

    def test_extra_params_beyond_contract_are_untouched(self) -> None:
        func = _func("def cb(ctx, auto_default):\n    return 1\n")
        c = CallableContract(params=["ClassDefContext"], ret="bool")
        # Only the aligned first param is filled; the arity-mismatched extra is left.
        assert align_contract(func, c) == {"ctx": "ClassDefContext", "return": "bool"}

    def test_ellipsis_params_fill_only_return(self) -> None:
        func = _func("def cb(a, b):\n    return 1\n")
        c = CallableContract(params=None, ret="int")
        assert align_contract(func, c) == {"return": "int"}

    def test_more_contract_params_than_function_params(self) -> None:
        func = _func("def cb(ctx):\n    return 1\n")
        c = CallableContract(params=["A", "B"], ret="R")
        assert align_contract(func, c) == {"ctx": "A", "return": "R"}


class TestMergeContracts:
    def test_single_contract(self) -> None:
        c = CallableContract(params=["X"], ret="Y")
        assert merge_contracts([c]) == (c, "ok")

    def test_identical_contracts_merge(self) -> None:
        c1 = CallableContract(params=["X"], ret="Y")
        c2 = CallableContract(params=["X"], ret="Y")
        assert merge_contracts([c1, c2]) == (c1, "ok")

    def test_conflicting_return_types(self) -> None:
        c1 = CallableContract(params=["ClassDefContext"], ret="None")
        c2 = CallableContract(params=["ClassDefContext"], ret="bool")
        result, reason = merge_contracts([c1, c2])
        assert result is None
        assert reason == "conflict"

    def test_conflicting_param_types(self) -> None:
        c1 = CallableContract(params=["A"], ret="R")
        c2 = CallableContract(params=["B"], ret="R")
        result, reason = merge_contracts([c1, c2])
        assert result is None
        assert reason == "conflict"

    def test_empty_yields_no_contract(self) -> None:
        assert merge_contracts([]) == (None, "no_contract")


class TestApplyContractPropagationIntegration:
    """End-to-end pins through the full Jedi engine (mirrors test_override_inference.py)."""

    def test_dead_end_callback_param_filled_params_only(self) -> None:
        """Dead-end callback adopts hook contract params, not its return (bool must not appear)."""
        source = textwrap.dedent(
            """
            from typing import Callable

            class Base:
                def get_hook(self, fullname: str) -> Callable[[int], bool] | None:
                    raise NotImplementedError

            class Sub(Base):
                def get_hook(self, fullname):
                    return callback

            def callback(x):
                return str(x)
            """
        )
        result = JediInferenceEngine(Settings()).infer_types(source)

        scope = _scope(result, "callback")
        assert scope.parameters["x"].type_str == "int"
        assert scope.parameters["x"].source == TypeSource.INHERITED
        assert scope.return_type is not None
        assert scope.return_type.type_str != "bool"

    def test_already_typed_param_is_never_overwritten(self) -> None:
        """Fill-only: already-typed callback param stays inferred, ignoring the hook's contract."""
        source = textwrap.dedent(
            """
            from typing import Callable

            class Base:
                def get_hook(self, fullname: str) -> Callable[[int], bool] | None:
                    raise NotImplementedError

            class Sub(Base):
                def get_hook(self, fullname):
                    return callback

            def callback(x: str):
                return x
            """
        )
        result = JediInferenceEngine(Settings()).infer_types(source)

        scope = _scope(result, "callback")
        assert scope.parameters["x"].type_str == "str"
        assert scope.parameters["x"].source != TypeSource.INHERITED

    @staticmethod
    def _write_cross_file_fixture(tmp_path, callbacks_source: str):
        """Write 3-file fixture: callbacks.py (analyzed), plugin.py hook subclass, base.py base."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "base.py").write_text(
            textwrap.dedent(
                """
                from typing import Callable

                class Base:
                    def get_hook(self, fullname: str) -> Callable[[int], bool] | None:
                        raise NotImplementedError
                """
            )
        )
        (pkg / "plugin.py").write_text(
            textwrap.dedent(
                """
                from pkg.base import Base
                from pkg.callbacks import my_callback

                class Sub(Base):
                    def get_hook(self, fullname):
                        return my_callback
                """
            )
        )
        callbacks_file = pkg / "callbacks.py"
        callbacks_file.write_text(callbacks_source)
        return callbacks_file

    def test_cross_file_hook_fills_local_dead_end_callback_params(self, tmp_path) -> None:
        """Dead-end callback params filled from remote (other-file) hook contract; params only."""
        callbacks_source = textwrap.dedent(
            """
            def my_callback(x):
                return str(x)
            """
        )
        callbacks_file = self._write_cross_file_fixture(tmp_path, callbacks_source)

        result = JediInferenceEngine(Settings()).infer_types(
            callbacks_source, path=str(callbacks_file), project_root=str(tmp_path)
        )

        scope = _scope(result, "my_callback")
        assert scope.parameters["x"].type_str == "int"
        assert scope.parameters["x"].source == TypeSource.INHERITED
        # Params only: the contract's declared return (bool) must never appear.
        assert scope.return_type is None or scope.return_type.type_str != "bool"

    def test_cross_file_search_skips_already_typed_functions(self, tmp_path) -> None:
        """Fill-only cross-file: already-typed callback isn't a dead-end candidate, untouched."""
        callbacks_source = textwrap.dedent(
            """
            def my_callback(x: str):
                return x
            """
        )
        callbacks_file = self._write_cross_file_fixture(tmp_path, callbacks_source)

        result = JediInferenceEngine(Settings()).infer_types(
            callbacks_source, path=str(callbacks_file), project_root=str(tmp_path)
        )

        scope = _scope(result, "my_callback")
        assert scope.parameters["x"].type_str == "str"
        assert scope.parameters["x"].source != TypeSource.INHERITED

    def test_nested_def_return_does_not_leak_hook_contract_same_file(self) -> None:
        """Wrong-fill guard: nested def return can't adopt contract, but the hook's return does."""
        source = textwrap.dedent(
            """
            from typing import Callable

            class Base:
                def get_hook(self, fullname: str) -> Callable[[int], bool] | None:
                    raise NotImplementedError

            class Sub(Base):
                def get_hook(self, fullname):
                    def inner():
                        return nested_callback
                    inner()
                    return real_callback

            def real_callback(x):
                return str(x)

            def nested_callback(y):
                return str(y)
            """
        )
        result = JediInferenceEngine(Settings()).infer_types(source)

        real_scope = _scope(result, "real_callback")
        assert real_scope.parameters["x"].type_str == "int"
        assert real_scope.parameters["x"].source == TypeSource.INHERITED

        nested_scope = _scope(result, "nested_callback")
        assert nested_scope.parameters["y"].source != TypeSource.INHERITED

    def test_cross_file_nested_def_return_does_not_leak_hook_contract(self, tmp_path) -> None:
        """Wrong-fill via cross-file indexer: remote hook returns candidate only from nested def."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "base.py").write_text(
            textwrap.dedent(
                """
                from typing import Callable

                class Base:
                    def get_hook(self, fullname: str) -> Callable[[int], bool] | None:
                        raise NotImplementedError
                """
            )
        )
        (pkg / "plugin.py").write_text(
            textwrap.dedent(
                """
                from pkg.base import Base
                from pkg.callbacks import nested_callback

                class Sub(Base):
                    def get_hook(self, fullname):
                        def inner():
                            return nested_callback
                        inner()
                """
            )
        )
        callbacks_source = textwrap.dedent(
            """
            def nested_callback(y):
                return str(y)
            """
        )
        callbacks_file = pkg / "callbacks.py"
        callbacks_file.write_text(callbacks_source)

        result = JediInferenceEngine(Settings()).infer_types(
            callbacks_source, path=str(callbacks_file), project_root=str(tmp_path)
        )

        scope = _scope(result, "nested_callback")
        assert scope.parameters["y"].source != TypeSource.INHERITED


def _dead_end_script_and_scope_tree() -> tuple[jedi.Script, ScopeTree]:
    """Same-file dead end (untyped param, no hook); stage-two cross-file walk left to run/skip."""
    source = textwrap.dedent(
        """
        def standalone(x):
            return x
        """
    )
    tree = ast.parse(source)
    script = jedi.Script(source)
    scope_tree = build_scope_tree(script, tree)
    return script, scope_tree


class TestContractPropagationCrossFileToggle:
    """enable_cross_file skips the _cross_file_contracts walk; same-file propagation applies."""

    def test_apply_contract_propagation_accepts_enable_cross_file(self):
        sig = inspect.signature(apply_contract_propagation)
        assert "enable_cross_file" in sig.parameters
        assert sig.parameters["enable_cross_file"].default is True

    def test_cross_file_contracts_skipped_when_disabled(self, monkeypatch):
        """enable_cross_file=False must never invoke the project-wide walk."""
        script, scope_tree = _dead_end_script_and_scope_tree()
        mock_cross_file = MagicMock(return_value={})
        monkeypatch.setattr(contract_propagation, "_cross_file_contracts", mock_cross_file)

        apply_contract_propagation(script, scope_tree, enable_cross_file=False)

        mock_cross_file.assert_not_called()

    def test_cross_file_contracts_invoked_when_enabled(self, monkeypatch):
        """enable_cross_file=True runs walk for dead-end candidate, proving False case gates it."""
        script, scope_tree = _dead_end_script_and_scope_tree()
        mock_cross_file = MagicMock(return_value={})
        monkeypatch.setattr(contract_propagation, "_cross_file_contracts", mock_cross_file)

        apply_contract_propagation(script, scope_tree, enable_cross_file=True)

        mock_cross_file.assert_called_once()
