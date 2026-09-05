"""End-to-end insert: a cross-file, locally-unimported type gets annotated + imported."""

from pathlib import Path

from injector import Injector

from fangtype.container import FangtypeModule
from fangtype.workflow import TypeAnnotationWorkflow


async def test_insert_adds_import_for_cross_file_type(tmp_path: Path) -> None:
    # helpers.make_amount returns a Decimal; main.py never imports Decimal itself.
    (tmp_path / "helpers.py").write_text(
        "from decimal import Decimal\n\n\ndef make_amount() -> Decimal:\n    return Decimal(1)\n"
    )
    main = tmp_path / "main.py"
    source = "from helpers import make_amount\n\n\ndef f():\n    m = make_amount()\n    return m\n"
    main.write_text(source)

    workflow = Injector([FangtypeModule()]).get(TypeAnnotationWorkflow)
    workflow._settings.project_root = str(tmp_path)  # let Jedi resolve the sibling module

    modified, inserted, _reasons, _msg = await workflow.insert_all_types(source, str(main))

    assert "m: Decimal" in modified
    assert "from decimal import Decimal" in modified
    assert inserted >= 1
