"""Run mypy in a subprocess.

Out-of-process on purpose: in-process ``mypy.api.run`` leaks RSS (~5 MB/run) in a long-lived
server. The dmypy daemon was the previous answer, but it only supports ``--follow-imports``
``normal``/``error``: ``error`` cannot see project imports, and under ``normal`` the daemon never
re-checks our synthetic probe, silently returning the first run's verdict forever.
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

# Caps a hung mypy so a validation fails instead of pinning a worker thread forever.
_RUN_TIMEOUT_SECONDS = 120.0


def _child_process_env() -> dict[str, str]:
    """Build the environment for the spawned mypy child process."""
    env = dict(os.environ)
    libs = env.get("FANGTYPE_BUNDLED_LIBS")
    if not libs:
        return env
    inherited = [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p]
    ordered: list[str] = []
    for path in [libs, *inherited]:
        if path not in ordered:
            ordered.append(path)
    env["PYTHONPATH"] = os.pathsep.join(ordered)
    return env


def _cache_dir(cache_key: str | None) -> str:
    """A stable per-project cache dir; a cold mypy build over a real project costs ~12s."""
    digest = hashlib.sha256((cache_key or "default").encode()).hexdigest()[:16]
    try:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
        path = base / "fangtype" / "mypy" / digest
        path.mkdir(parents=True, exist_ok=True)
    except OSError as e:  # no home, read-only fs: a cold cache still works, it's just slower
        logger.warning("Could not use the persistent mypy cache (%s); using a temp dir", e)
        return tempfile.mkdtemp(prefix="fangtype_mypy_cache_")
    return str(path)


class MypyRunner:
    """Runs `python -m mypy -c <code>`, reusing one on-disk cache across calls."""

    def __init__(self, flags: list[str], cache_key: str | None = None) -> None:
        self._flags = list(flags)
        self._cache_dir = _cache_dir(cache_key)
        # mypy has no cross-process cache locking, so serialize runs sharing our cache dir.
        self._lock = threading.Lock()

    def run(self, code: str) -> tuple[str, str, int]:
        """Type-check `code`, returning (stdout, stderr, exit_code); errors report as `<string>`."""
        cmd = [
            sys.executable,
            "-m",
            "mypy",
            *self._flags,
            "--cache-dir",
            self._cache_dir,
            "-c",
            code,
        ]
        with self._lock:
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=_RUN_TIMEOUT_SECONDS,
                    env=_child_process_env(),
                )
            except (OSError, subprocess.SubprocessError) as e:
                logger.warning("Could not run mypy: %s", e)
                return "", str(e), 2
        return proc.stdout, proc.stderr, proc.returncode
