"""get_import_hints exposes per-(line,name) imports for insertable variable bindings."""

from fangtype.inference.jedi.engine import JediInferenceEngine
from fangtype.utils.settings import Settings


def test_get_import_hints_variables() -> None:
    src = "from decimal import Decimal\n\ndef f():\n    m = Decimal(3)\n    return m\n"
    result = JediInferenceEngine(Settings()).infer_types(src)
    hints = result.get_import_hints()
    assert ("decimal", "Decimal") in hints.values()
    assert any(name == "m" for (_line, name) in hints)


def test_get_import_hints_empty_for_builtins() -> None:
    src = "def f():\n    n = 5\n    return n\n"
    result = JediInferenceEngine(Settings()).infer_types(src)
    assert result.get_import_hints() == {}
