"""The engine adds imports for applied annotations, dedups, and never for a bare-hint plan."""

from fangtype.insertion.engine import InsertionEngine
from fangtype.insertion.target_factory import create_variable_target
from fangtype.insertion.types import TargetType


def test_applied_annotation_adds_import() -> None:
    source = "def f():\n    m = make()\n    return m\n"
    target = create_variable_target(
        "m",
        "Decimal",
        2,
        target_type=TargetType.VARIABLE_SIMPLE,
        import_hint=("decimal", "Decimal"),
    )
    result = InsertionEngine().insert([target], source)
    assert result.success
    assert "from decimal import Decimal" in result.modified_source
    assert "m: Decimal" in result.modified_source


def test_existing_import_not_duplicated() -> None:
    source = "from decimal import Decimal\n\ndef f():\n    m = make()\n    return m\n"
    target = create_variable_target(
        "m",
        "Decimal",
        4,
        target_type=TargetType.VARIABLE_SIMPLE,
        import_hint=("decimal", "Decimal"),
    )
    result = InsertionEngine().insert([target], source)
    assert result.modified_source.count("from decimal import Decimal") == 1


def test_no_hint_adds_no_import() -> None:
    source = "def f():\n    n = 5\n    return n\n"
    target = create_variable_target("n", "int", 2, target_type=TargetType.VARIABLE_SIMPLE)
    result = InsertionEngine().insert([target], source)
    assert "import" not in result.modified_source


def test_a_name_the_file_already_defines_is_not_imported_over() -> None:
    """A synthesised import must never shadow a class the analysed file defines itself.

    mypy reports the collision as no-redef on the class statement, which hosts no annotation
    target, so the assignability gate cannot see it and the file would ship shadowed.
    """
    source = "class Generator:\n    pass\n\n\ndef f():\n    g = Generator()\n    return g\n"
    target = create_variable_target(
        "g",
        "Generator",
        6,
        target_type=TargetType.VARIABLE_SIMPLE,
        import_hint=("collections.abc", "Generator"),
    )
    result = InsertionEngine().insert([target], source)
    assert "g: Generator" in result.modified_source
    assert "from collections.abc import Generator" not in result.modified_source
