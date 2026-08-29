"""The two removal sources must produce the same corpus, byte for byte.

Preparation reaches the removal engine over ``fangtype/previewRemovals`` and
``fangtype/removeTypesInFile`` rather than by constructing a ``RemovalEngine`` in
process, so the stripped tree the mypy-corpus evaluation scores against now depends on a
protocol round trip. Every published number rests on that tree. This test is what says
the change of route moved nothing: it prepares the same corpus twice into two separate
workspaces, once in process and once over a real server subprocess, and demands the
stripped text and every manifest field agree exactly.

It starts a server, so it lives beside the other integration tests rather than in the
unit suite.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING

import pytest

from benchmark.mypy_eval.prepare import prepare_mypy_workspace
from benchmark.mypy_eval.removal_source import InProcessRemovalSource

if TYPE_CHECKING:
    from pathlib import Path

TYPED_SOURCE = "def f(x: int) -> str:\n    y: int = 1\n    return str(x) + str(y)\n"
UNTYPED_SOURCE = "def g(z):\n    return z\n"


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    """One annotated file and one with nothing to remove.

    The unannotated file is the case the two sources could most easily disagree on. The
    in-process source runs the LibCST pass and keeps its output, while the LSP source
    takes the client's early return and keeps the source verbatim, because
    ``removeTypesInFile`` carries no edit when there is nothing to remove.
    """
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "typed.py").write_text(TYPED_SOURCE, encoding="utf-8")
    (root / "untyped.py").write_text(UNTYPED_SOURCE, encoding="utf-8")
    return root


def test_lsp_preparation_matches_the_in_process_one(corpus: Path, tmp_path: Path) -> None:
    """Same corpus, two transports, identical stripped tree and identical manifest."""
    in_process_dir = tmp_path / "in_process"
    over_lsp_dir = tmp_path / "over_lsp"

    in_process = prepare_mypy_workspace(
        in_process_dir, mypy_dir=corpus, removal=InProcessRemovalSource()
    )
    # No ``removal=``, so this arm goes through ``default_removal_source`` and drives a
    # real fangtype-server over stdio, exactly as a benchmark run does.
    over_lsp = prepare_mypy_workspace(over_lsp_dir, mypy_dir=corpus)

    assert in_process.reused is False
    assert over_lsp.reused is False
    assert in_process.error_file_count == 0
    assert over_lsp.error_file_count == 0

    for tree in ("original", "stripped"):
        for relative in ("typed.py", "untyped.py"):
            expected = (in_process_dir / tree / relative).read_bytes()
            actual = (over_lsp_dir / tree / relative).read_bytes()
            assert actual == expected, f"{tree}/{relative} differs between the two sources"

    for relative in ("typed.py", "untyped.py"):
        expected = (in_process_dir / "coldstart" / corpus.name / relative).read_bytes()
        actual = (over_lsp_dir / "coldstart" / corpus.name / relative).read_bytes()
        assert actual == expected, f"coldstart/{relative} differs between the two sources"

    # ``MypyFileManifest`` and ``MypyTargetManifest`` are plain dataclasses, so this
    # compares every field of every target, not merely the counts.
    assert [asdict(entry) for entry in over_lsp.files] == [
        asdict(entry) for entry in in_process.files
    ]
    assert over_lsp.typed_file_count == in_process.typed_file_count
    assert over_lsp.untyped_file_count == in_process.untyped_file_count
    assert over_lsp.total_python_files == in_process.total_python_files

    # The annotated file really was stripped, so the agreement above is not two sources
    # both doing nothing.
    assert in_process.typed_file_count == 1
    assert "int" not in (over_lsp_dir / "stripped" / "typed.py").read_text(encoding="utf-8")
    assert (over_lsp_dir / "stripped" / "untyped.py").read_text(encoding="utf-8") == UNTYPED_SOURCE
