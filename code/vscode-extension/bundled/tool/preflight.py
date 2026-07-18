"""Cheap dependency preflight for the Fangtype server.

Run by the extension under the SAME interpreter + env as the real launch. Uses
``importlib.util.find_spec`` (which locates a module without importing it, so heavy
packages like mypy are never executed) to report which of the server's direct
third-party dependencies are missing. ``fangtype`` itself ships in the VSIX, so a
missing name here means the interpreter's environment lacks a dependency.

Output contract: print the missing top-level import names, comma-separated, to
stdout and exit 1 when any are absent; print nothing and exit 0 when all resolve.
"""

from __future__ import annotations

import importlib.util
import sys

# Direct third-party imports the server needs at import time. `librt` is mypy's
# native accelerator (mypy hard-imports `librt.base64`), so probe it explicitly.
#
# Limitation: `find_spec` locates a package without importing it, so it can't
# detect a package that resolves but whose OWN hard imports are broken/missing
# (e.g. a corrupt or partially-installed dependency of one of these). The
# dominant real-world case -- a fresh interpreter with none of these packages
# installed at all -- is fully caught since every top-level name is absent;
# `librt` is probed explicitly above because it's the one realistic
# partial-miss (mypy present, its native accelerator not).
REQUIRED = ("pygls", "libcst", "mypy", "jedi", "injector", "librt")


def main() -> int:
    missing = [name for name in REQUIRED if importlib.util.find_spec(name) is None]
    if missing:
        sys.stdout.write(",".join(missing))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
