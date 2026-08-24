"""A concrete type Jedi resolves yields an import_hint on the variable's TypeInfo."""

from fangtype.inference.jedi.engine import JediInferenceEngine
from fangtype.utils.settings import Settings


def _var_type_info(source: str, name: str):
    result = JediInferenceEngine(Settings()).infer_types(source)
    for scope in result.scope_tree.scopes_by_id.values():
        if name in scope.variables:
            return scope.variables[name]
    raise AssertionError(f"{name} not found")


def test_local_decimal_binding_has_import_hint() -> None:
    src = "from decimal import Decimal\n\ndef f():\n    m = Decimal(3)\n    return m\n"
    ti = _var_type_info(src, "m")
    assert ti.type_str == "Decimal"
    assert ti.import_hint == ("decimal", "Decimal")


def test_builtin_binding_has_no_import_hint() -> None:
    src = "def f():\n    n = 5\n    return n\n"
    ti = _var_type_info(src, "n")
    assert ti.import_hint is None


def test_class_defined_in_the_analysed_source_has_no_import_hint() -> None:
    # Jedi names it __main__.Node in memory and <modname>.Node on disk. Either way it is
    # already bound in the file being annotated, so importing it would be a self-import.
    src = "class Node:\n    pass\n\n\nn = Node()\n"
    ti = _var_type_info(src, "n")
    assert ti.type_str == "Node"
    assert ti.import_hint is None
