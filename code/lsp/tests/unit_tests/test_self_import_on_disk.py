"""Annotating a real on-disk module must not make it import itself.

The in-memory tests reach this through Jedi's ``__main__`` naming, which reads like an
artefact of the pathless script. It is not. With a real file inside a real project root
Jedi names the module after the file, so the same hint writes ``from realmod import Node``
into ``realmod.py``.
"""

import asyncio
from pathlib import Path

from fangtype.container import build_container
from fangtype.workflow import TypeAnnotationWorkflow

_SOURCE = (
    "class Node:\n"
    "    def link(self, other):\n"
    "        return other\n"
    "\n"
    "\n"
    "n = Node()\n"
    "n.link(Node())\n"
)


def test_on_disk_module_is_not_made_to_import_itself(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'probe'\n")
    module = tmp_path / "realmod.py"
    module.write_text(_SOURCE)

    workflow = build_container("jedi").get(TypeAnnotationWorkflow)
    modified, _var_count, _func_count, _msg = asyncio.run(
        workflow.insert_all_types(_SOURCE, str(module))
    )

    assert "from realmod import" not in modified
    assert "import realmod" not in modified
    # The annotations themselves still land, so the guard is not just suppressing output.
    assert 'other: "Node"' in modified
