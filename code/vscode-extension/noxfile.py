"""Nox sessions that vendor the Fangtype server + deps into ``bundled/libs``.

Every session runs with ``venv_backend="none"`` so it executes in the *ambient*
CI/Nix Python rather than a nox-created virtualenv. That matters because
``pip install -t bundled/libs`` writes into the working tree, never the
read-only Nix store, so vendoring works inside ``nix develop``.

``setup`` vendors ONLY the pure-Python ``fangtype`` package (installed
``--no-deps``) into ``bundled/libs`` and ships the hash-pinned
``requirements.txt`` lockfile alongside the bootstrap. Third-party deps
(libcst/mypy/librt native wheels, plus jedi/pygls/injector) are intentionally
NOT vendored: they are ABI/version-specific and are instead resolved from the
user's own interpreter (``importStrategy=fromEnvironment``), which the
extension prompts to install via that lockfile when missing. Because nothing
native ships in the bundle, ``build_package`` produces a single universal
``.vsix`` (any OS, any CPython 3.x) rather than a per-platform one.

Sessions:
    setup            vendor the pure-Python fangtype package + requirements.txt into bundled/
    update_packages  regenerate the committed, pinned (un-hashed) requirements.txt lockfile
    build_package    esbuild the extension and produce a universal .vsix
    tests / lint     thin CI entrypoints delegating to the server's pytest/ruff/mypy
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import nox

EXT_DIR = Path(__file__).parent.resolve()
LSP_DIR = (EXT_DIR.parent / "lsp").resolve()
BUNDLED_LIBS = EXT_DIR / "bundled" / "libs"
REQUIREMENTS = EXT_DIR / "requirements.txt"

# The interpreter running nox *is* the ambient CI/Nix Python; vendoring must use
# its pip so the resolved wheels' ABI/platform tags match the interpreter the
# extension will later launch the server with.
PYTHON = sys.executable


def _prune_bytecode(root: Path) -> None:
    """Delete ``__pycache__`` dirs and ``*.pyc`` files under ``root``.

    Keeps the vendored tree lean and reproducible in the shipped VSIX.
    """
    for pycache in root.rglob("__pycache__"):
        shutil.rmtree(pycache, ignore_errors=True)
    for pyc in root.rglob("*.pyc"):
        pyc.unlink(missing_ok=True)


@nox.session(venv_backend="none")
def setup(session: nox.Session) -> None:
    """Vendor ONLY the pure-Python fangtype package into ``bundled/libs`` and ship
    the dep lockfile alongside the bootstrap.

    Third-party deps (libcst/mypy/librt native wheels, plus jedi/pygls/injector)
    are intentionally NOT vendored: they are ABI/version-specific and are resolved
    from the user's interpreter (importStrategy=fromEnvironment). Shipping only the
    pure-Python fangtype package keeps the VSIX universal (any OS, any CPython 3.x).
    """
    if not REQUIREMENTS.is_file():
        session.error(
            f"{REQUIREMENTS} is missing -- run `nox -s update_packages` first."
        )

    if BUNDLED_LIBS.exists():
        shutil.rmtree(BUNDLED_LIBS)
    BUNDLED_LIBS.mkdir(parents=True)

    # The fangtype package only, built from source, WITHOUT its dependencies.
    session.run(
        PYTHON,
        "-m",
        "pip",
        "install",
        "-t",
        str(BUNDLED_LIBS),
        "--no-deps",
        str(LSP_DIR),
        external=True,
    )
    _prune_bytecode(BUNDLED_LIBS)

    # Ship the hash-pinned dep lockfile next to the bootstrap so the extension's
    # "Install dependencies" action can `pip install -r` it into the interpreter.
    shutil.copyfile(REQUIREMENTS, EXT_DIR / "bundled" / "requirements.txt")


@nox.session(venv_backend="none")
def update_packages(session: nox.Session) -> None:
    """Regenerate the committed, pinned (un-hashed) ``requirements.txt`` lockfile.

    The dependency source of truth is ``../lsp/pyproject.toml``'s
    ``[project.dependencies]`` -- there is intentionally no ``requirements.in``.
    Run from ``EXT_DIR`` with relative paths so the committed lockfile's header
    is reproducible (no absolute, machine-specific paths).

    NOT ``--generate-hashes``: this file is only consumed by the extension's
    "Install dependencies" action (``pip install -r`` into the user's
    interpreter), cross-platform. Hashes force pip into ``--require-hashes``
    mode, which demands the *complete* dependency closure be pinned -- but this
    file is resolved on one OS/Python, so a different platform (e.g. Windows)
    needs an extra transitive dep (``colorama`` etc.) that isn't listed, and pip
    aborts. Un-hashed, pip resolves those platform-specific extras itself.
    """
    session.chdir(str(EXT_DIR))
    pyproject = os.path.relpath(LSP_DIR / "pyproject.toml", EXT_DIR)
    session.run(
        PYTHON,
        "-m",
        "piptools",
        "compile",
        "--output-file",
        "requirements.txt",
        pyproject,
        external=True,
    )


@nox.session(venv_backend="none")
def build_package(session: nox.Session) -> None:
    """Build the extension bundle and package a single universal ``.vsix``.

    Runs ``setup`` first to vendor the pure-Python ``fangtype`` package into
    ``bundled/libs``. Since nothing native ships in the bundle, the VSIX is not
    tied to a particular OS or CPython minor version -- no ``--target`` is
    passed to ``vsce package``.
    """
    setup(session)
    session.chdir(str(EXT_DIR))
    session.run("npm", "ci", external=True)
    session.run("npm", "run", "build", external=True)
    # --out pins a stable filename: CI's artifacts glob and the create-release
    # asset link both hardcode `fangtype.vsix`.
    session.run(
        "npx",
        "vsce",
        "package",
        "--out",
        "fangtype.vsix",
        external=True,
    )


@nox.session(venv_backend="none")
def tests(session: nox.Session) -> None:
    """CI entrypoint: run the server's pytest suite.

    A thin wrapper only -- local development keeps using the Nix/pre-commit gate.
    """
    session.chdir(str(LSP_DIR))
    session.run(PYTHON, "-m", "pytest", *session.posargs, external=True)


@nox.session(venv_backend="none")
def lint(session: nox.Session) -> None:
    """CI entrypoint: ruff + mypy over the server source (thin wrapper)."""
    session.chdir(str(LSP_DIR))
    session.run(PYTHON, "-m", "ruff", "check", "src", external=True)
    session.run(PYTHON, "-m", "mypy", "src", external=True)
