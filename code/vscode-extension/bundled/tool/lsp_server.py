"""Fangtype language-server entrypoint, run from source under the user's interpreter.

The VS Code extension launches this file with the interpreter the user selected
through the Python extension (replacing the old PyInstaller binary). Before it
hands off to :func:`fangtype.server.main`, it arranges ``sys.path`` and, crucially,
exports ``PYTHONPATH`` so that any child process the server spawns (notably the
``dmypy`` daemon) resolves the same ``fangtype`` package and its dependencies.

Layout::

    bundled/
      tool/   <- this file (lsp_server.py, lsp_runner.py)
      libs/   <- third-party deps + the fangtype package (populated in Phase 3)

``bundled/libs`` does not exist in a source checkout, so every step degrades
gracefully when it is absent (``fromEnvironment`` then supplies dependencies
from the interpreter's own environment / an inherited ``PYTHONPATH``).
"""

from __future__ import annotations

import os
import sys

TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
BUNDLE_DIR = os.path.dirname(TOOL_DIR)
LIBS_DIR = os.path.join(BUNDLE_DIR, "libs")

# ``useBundled`` (default) prefers the bundled copies; ``fromEnvironment`` prefers
# whatever the launching interpreter already provides.
LS_IMPORT_STRATEGY = os.getenv("LS_IMPORT_STRATEGY", "useBundled")


def update_sys_path(path_to_add: str, strategy: str) -> None:
    """Add ``path_to_add`` to ``sys.path``, ordered by the import strategy.

    ``useBundled`` prepends (bundled deps take precedence); any other value —
    notably ``fromEnvironment`` — appends (the interpreter's environment wins).
    A missing or already-present directory is skipped so a source checkout, where
    ``bundled/libs`` has not been produced yet, is a no-op.

    Args:
        path_to_add: Directory to make importable.
        strategy: ``useBundled`` or ``fromEnvironment``.
    """
    if not path_to_add or not os.path.isdir(path_to_add) or path_to_add in sys.path:
        return
    if strategy == "useBundled":
        sys.path.insert(0, path_to_add)
    else:
        sys.path.append(path_to_add)


def export_pythonpath(dirs: list[str], strategy: str) -> None:
    """Merge ``dirs`` into the inherited ``PYTHONPATH`` and re-export it.

    Child processes inherit ``os.environ``, so writing the merged value back means
    the ``dmypy`` daemon (and anything else the server spawns) imports the same
    packages the server itself does. ``useBundled`` places ``dirs`` first, every
    other strategy places them last. Order is de-duplicated to keep the value tidy.

    Args:
        dirs: Directories to fold into ``PYTHONPATH``.
        strategy: ``useBundled`` or ``fromEnvironment``.
    """
    inherited = [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]
    ours = [d for d in dirs if d]
    merged = ours + inherited if strategy == "useBundled" else inherited + ours
    seen: set[str] = set()
    ordered = [p for p in merged if not (p in seen or seen.add(p))]
    os.environ["PYTHONPATH"] = os.pathsep.join(ordered)


# Make bundled dependencies importable in-process (no-op without a bundle), then
# export the resolved path so child processes inherit it.
update_sys_path(LIBS_DIR, LS_IMPORT_STRATEGY)
export_pythonpath([LIBS_DIR, TOOL_DIR], LS_IMPORT_STRATEGY)
# Only export the libs marker when a real bundle exists. In a source checkout
# (``fromEnvironment``) ``bundled/libs`` is absent, and exporting it would make
# ``dmypy_runner._child_process_env`` prepend a non-existent dir to the child
# PYTHONPATH; guarding on ``isdir`` keeps that env var meaningful.
if os.path.isdir(LIBS_DIR):
    os.environ["FANGTYPE_BUNDLED_LIBS"] = LIBS_DIR

from fangtype.server import main  # noqa: E402  (import after sys.path/env setup)

if __name__ == "__main__":
    main()
