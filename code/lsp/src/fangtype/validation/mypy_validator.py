"""Mypy-based type validator for checking type annotation correctness."""

import asyncio
import logging
import os
import re
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from injector import inject

from fangtype.utils.settings import Settings
from fangtype.validation.mypy_diagnostic import MypyDiagnostic
from fangtype.validation.mypy_runner import MypyRunner


@dataclass
class TypeValidationResult:
    """Result of validating one type annotation (type_str, is_valid, optional error_message)."""

    type_str: str
    is_valid: bool
    error_message: str | None = None


logger = logging.getLogger(__name__)

# Default mypy target version when the project interpreter's version can't be probed.
TARGET_PYTHON_VERSION = "3.12"

# Static mypy flags independent of the target env; version/executable are appended per-project.
_BASE_MYPY_FLAGS = [
    "--no-error-summary",
    "--no-color-output",
    "--show-column-numbers",  # Without this mypy omits the column and every diagnostic lands at 0
    "--disallow-untyped-defs",  # Report functions missing type annotations
    "--check-untyped-defs",  # Check bodies of untyped functions
    "--allow-untyped-calls",  # Allow calling untyped functions
    "--no-warn-return-any",  # Don't warn about Any returns
    "--allow-incomplete-defs",  # Allow partial annotations
    # Follow project imports so project types resolve to real types instead of Any; `silent` keeps
    # errors from the project's own files out of our output. `error` here was the bug: it made
    # every project import unresolvable.
    "--follow-imports=silent",
]

_VERSION_RE = re.compile(r"\d+\.\d+")


def _version_from_pyvenv_cfg(interpreter: str) -> str | None:
    """Read ``major.minor`` from a venv's ``pyvenv.cfg`` — no subprocess, instant, no AV stall."""
    cfg = Path(interpreter).parent.parent / "pyvenv.cfg"
    try:
        text = cfg.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() in ("version", "version_info"):
            m = _VERSION_RE.match(value.strip())
            if m:
                return m.group()
    return None


def _probe_python_version(interpreter: str) -> str | None:
    """Return ``interpreter``'s ``major.minor`` (e.g. ``3.12``), or ``None`` if undeterminable."""
    cfg_version = _version_from_pyvenv_cfg(interpreter)
    if cfg_version:
        return cfg_version
    try:
        proc = subprocess.run(
            [interpreter, "-c", "import sys;print(f'{sys.version_info[0]}.{sys.version_info[1]}')"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("Could not probe Python version for %r: %s", interpreter, e)
        return None
    out = proc.stdout.strip()
    if proc.returncode == 0 and _VERSION_RE.fullmatch(out):
        return out
    return None


# Match errors only from our own `-c` snippet (`<string>`); drop those from followed project files.
pattern = re.compile(
    r"^<string>:(\d+):(?:(\d+):)?\s*(error|warning|note):\s*(.+?)(?:\s+\[([^\]]+)\])?\s*$"
)


class MypyTypeValidator:
    """Mypy-backed validator: semantic type checking; async API runs blocking mypy in a thread."""

    # @inject leaks Any (overloads resolve to Any), tripping disallow_any_expr — ignore here.
    @inject  # type: ignore[misc]
    def __init__(self, settings: Settings) -> None:
        """Init the validator; flags/runner resolve lazily since project_interpreter lands later."""
        self._settings = settings
        self._flags: list[str] | None = None
        self._runner: MypyRunner | None = None
        # Guards check-then-construct in _ensure_runner and the teardown in close(); without it,
        # concurrent to_thread validations race the `is None` check and each build their own
        # MypyRunner (and worker subprocess), orphaning all but one.
        self._runner_lock = threading.Lock()

    def _mypy_flags(self) -> list[str]:
        """The resolved mypy flag list (cached), including per-project version/executable."""
        if self._flags is None:
            self._flags = self._build_flags()
        return self._flags

    def _build_flags(self) -> list[str]:
        """Build flags: base + version/executable so an isolated server resolves project imports."""
        self._export_mypy_path()
        interpreter = self._settings.project_interpreter
        version = (
            _probe_python_version(interpreter) if interpreter else None
        ) or TARGET_PYTHON_VERSION
        flags = [*_BASE_MYPY_FLAGS, "--python-version", version]
        if interpreter:
            flags += ["--python-executable", interpreter]
        return flags

    def _export_mypy_path(self) -> None:
        """Put the project root on MYPYPATH so the `-c` snippet can resolve first-party imports.

        mypy has no CLI equivalent for this, and the env is what the mypy child inherits.
        """
        root = self._settings.project_root
        if not root:
            return
        # ponytail: root + src/ covers flat and src layouts; read the project's mypy config if a
        # project ever needs a custom mypy_path.
        roots = [root]
        src = Path(root) / "src"
        if src.is_dir():
            roots.append(str(src))
        inherited = [p for p in os.environ.get("MYPYPATH", "").split(os.pathsep) if p]
        ordered: list[str] = []
        for path in [*roots, *inherited]:
            if path not in ordered:
                ordered.append(path)
        os.environ["MYPYPATH"] = os.pathsep.join(ordered)

    def _ensure_runner(self) -> MypyRunner:
        """Lazily build the mypy subprocess runner from the resolved flags (thread-safe).

        Known, bounded hazard: this only guards *construction*. A caller can still receive a
        runner here, have another thread call `close()` on this validator before the caller
        gets to `.run()`, and hand a closed runner a request. `MypyRunner._ensure_worker`
        respawns a worker for it regardless (it only checks whether ITS OWN process died, not
        whether `close()` was ever called), so the request still succeeds. `atexit` still reaps
        the respawned worker on interpreter exit, so this is a bounded resource leak on an
        unlucky shutdown race, not an orphaned process. Not fixed here: closing that window
        needs the runner itself to remember it was closed and refuse to respawn, which is a
        change to `MypyRunner`, not to this lock.
        """
        with self._runner_lock:
            if self._runner is None:
                self._runner = MypyRunner(
                    flags=self._mypy_flags(), cache_key=self._settings.project_root
                )
            return self._runner

    def _run_mypy_sync(self, code: str) -> tuple[str, str, int]:
        """Validate `code` in a mypy subprocess."""
        return self._ensure_runner().run(code)

    def close(self) -> None:
        """Terminate this validator's mypy worker subprocess, if one was built. Idempotent.

        Known, bounded hazard: this holds `_runner_lock` across `MypyRunner.close()`, which
        blocks on `MypyRunner`'s own lock behind any in-flight `run()` (up to
        `_RUN_TIMEOUT_SECONDS` plus the terminate grace period, so on the order of 35s worst
        case). `on_shutdown` in server.py calls this synchronously, so an LSP shutdown that
        used to return instantly can now block for that long if a validation is in flight.
        Bounded, not a hang; not fixed here because shrinking the lock scope would let a
        caller observe a runner mid-teardown.
        """
        with self._runner_lock:
            if self._runner is not None:
                self._runner.close()
                self._runner = None

    async def validate_file_full(self, source: str) -> list[MypyDiagnostic]:
        """Run mypy on the whole file, returning all diagnostics (empty if none)."""
        try:
            # Run in thread since mypy is blocking
            return await asyncio.to_thread(self._validate_file_full_sync, source)
        except asyncio.CancelledError:
            logger.info("Mypy file validation cancelled by client")
            raise

    def _validate_file_full_sync(self, source: str) -> list[MypyDiagnostic]:
        """Synchronous implementation of validate_file_full."""
        stdout, stderr, exit_code = self._run_mypy_sync(source)

        # Exit code 0 means no errors
        if exit_code == 0:
            return []

        # No output but non-zero exit - something went wrong
        if not stdout:
            self._log_empty_mypy_output(stderr, "file validation")
            return []

        # Parse mypy output
        return self._parse_mypy_output(stdout)

    def _parse_mypy_output(self, output: str) -> list[MypyDiagnostic]:
        """Parse mypy stdout (SOURCE:LINE:COL: SEVERITY: MSG [CODE]) into diags; skip foreign."""
        diagnostics: list[MypyDiagnostic] = []

        for line in output.strip().split("\n"):
            match = pattern.match(line)
            if not match:
                # Skip lines that don't match (e.g., context lines)
                continue

            # Narrow match.groups() to the concrete 5-group shape (col + error_code optional).
            groups = cast("tuple[str, str | None, str, str, str | None]", match.groups())
            line_num_str, col_str, severity, message, error_code = groups

            line_num = int(line_num_str)
            # Mypy columns are 1-based on the wire; MypyDiagnostic.column is 0-based.
            column = max(int(col_str) - 1, 0) if col_str else 0

            diagnostics.append(
                MypyDiagnostic(
                    line=line_num,
                    column=column,
                    message=message.strip(),
                    error_code=error_code,
                    severity=severity,
                )
            )

        return diagnostics

    def _log_empty_mypy_output(self, stderr: str, context: str) -> None:
        """Log warning when mypy returns non-zero exit but no stdout."""
        logger.warning(f"Mypy {context} failed with no output: {stderr}")
