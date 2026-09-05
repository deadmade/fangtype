"""A Callable inferred for a parameter or a return earns its import, exactly as a variable does.

The corpus pair these mirror is TypeEvalPy's ``args/call`` against ``args/assigned_call``. The
second one passes today only because a *variable* bound to a function writes the import first,
which is the accident that hid the defect on the parameter and return paths.
"""

from pathlib import Path

from injector import Injector

from fangtype.container import FangtypeModule
from fangtype.inference.jedi.engine import JediInferenceEngine
from fangtype.utils.settings import Settings
from fangtype.workflow import TypeAnnotationWorkflow

# args/call: `a` is a parameter Jedi resolves to a function, and no variable in the file is
# Callable, so nothing else writes the import.
_CALLABLE_PARAM = (
    "def param_func():\n"
    '    return "Hello from param_func"\n'
    "\n\n"
    "def func(a):\n"
    "    return a()\n"
    "\n\n"
    "b = func(param_func)\n"
)

# args/assigned_call: the same shape plus `b = param_func`, whose variable hint already works.
_CALLABLE_PARAM_WITH_VARIABLE = (
    "def param_func():\n"
    '    return "Hello from param_func"\n'
    "\n\n"
    "def func(a):\n"
    "    return a()\n"
    "\n\n"
    "b = param_func\n"
    "c = func(b)\n"
)

_CALLABLE_RETURN = (
    "def param_func():\n"
    '    return "Hello from param_func"\n'
    "\n\n"
    "def outer():\n"
    "    return param_func\n"
)


def _infer(source: str):
    return JediInferenceEngine(Settings()).infer_types(source)


def test_parameter_hint_reaches_the_function_hint_map() -> None:
    hints = _infer(_CALLABLE_PARAM).get_function_import_hints()
    assert ("collections.abc", "Callable") in hints.values()
    assert any(key[2] == "a" for key in hints)


def test_return_type_info_carries_an_import_hint() -> None:
    result = _infer(_CALLABLE_RETURN)
    scope = next(
        s
        for s in result.scope_tree.get_all_function_scopes()
        if s.return_type is not None and "outer" in s.scope_id
    )
    assert scope.return_type.type_str == "Callable"
    assert scope.return_type.import_hint == ("collections.abc", "Callable")


def test_every_hint_key_exists_in_the_flattened_validation_space() -> None:
    """No hint may be keyed to a function, parameter or return the insertions do not carry.

    _validate_function_insertions flattens to (line0, func_name, param_name) with "return" as
    the return sentinel. A hint outside that space is a hint the probe silently never applies.
    """
    result = _infer(_CALLABLE_PARAM)
    insertions = result.get_function_insertions()
    flat: set[tuple[int, str, str]] = set()
    for (line, fname), info in insertions.items():
        flat.update((line, fname, param_name) for param_name in info["params"])
        if info["return_type"] is not None:
            flat.add((line, fname, "return"))

    assert result.get_function_import_hints().keys() <= flat


def test_the_return_sentinel_is_keyed() -> None:
    hints = _infer(_CALLABLE_RETURN).get_function_import_hints()
    assert hints[(4, "outer", "return")] == ("collections.abc", "Callable")


async def test_insert_writes_the_import_for_a_callable_parameter(tmp_path: Path) -> None:
    main = tmp_path / "main.py"
    main.write_text(_CALLABLE_PARAM)

    workflow = Injector([FangtypeModule()]).get(TypeAnnotationWorkflow)
    workflow._settings.project_root = str(tmp_path)

    modified, inserted, _reasons, _msg = await workflow.insert_all_types(_CALLABLE_PARAM, str(main))

    assert "a: Callable" in modified
    assert "from collections.abc import Callable" in modified
    assert inserted >= 1


async def test_a_good_sibling_parameter_survives_beside_a_callable_one(tmp_path: Path) -> None:
    """The co-located-victim regression, and the reason the probe and the target must land together.

    The gate blames a source line rather than an annotation, so an unimportable `Callable` on a
    def line takes every other annotation on that line down with it. Fixing only the probe would
    let the parameter reach insertion without its import and make this strictly worse than the
    unfixed state.
    """
    source = (
        "def param_func():\n"
        '    return "Hello from param_func"\n'
        "\n\n"
        "def func(a, n):\n"
        "    return a() * n\n"
        "\n\n"
        "b = func(param_func, 3)\n"
    )
    main = tmp_path / "main.py"
    main.write_text(source)

    workflow = Injector([FangtypeModule()]).get(TypeAnnotationWorkflow)
    workflow._settings.project_root = str(tmp_path)

    modified, _inserted, _reasons, _msg = await workflow.insert_all_types(source, str(main))

    assert "a: Callable" in modified
    assert "n: int" in modified
    assert "from collections.abc import Callable" in modified


async def test_a_generator_return_earns_its_import(tmp_path: Path) -> None:
    source = "def gen(n):\n    for i in range(n):\n        yield i\n\n\ng = gen(3)\n"
    main = tmp_path / "main.py"
    main.write_text(source)

    workflow = Injector([FangtypeModule()]).get(TypeAnnotationWorkflow)
    workflow._settings.project_root = str(tmp_path)

    modified, _inserted, _reasons, _msg = await workflow.insert_all_types(source, str(main))

    assert "-> Generator" in modified
    assert "from collections.abc import Generator" in modified


async def test_the_variable_control_still_passes(tmp_path: Path) -> None:
    # This one already worked before the fix. It must not regress, and it is what proves the
    # parameter case was failing for want of an import rather than for want of a type.
    main = tmp_path / "main.py"
    main.write_text(_CALLABLE_PARAM_WITH_VARIABLE)

    workflow = Injector([FangtypeModule()]).get(TypeAnnotationWorkflow)
    workflow._settings.project_root = str(tmp_path)

    modified, _inserted, _reasons, _msg = await workflow.insert_all_types(
        _CALLABLE_PARAM_WITH_VARIABLE, str(main)
    )

    assert "from collections.abc import Callable" in modified
    assert modified.count("from collections.abc import Callable") == 1
