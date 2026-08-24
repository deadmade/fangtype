"""Run mypy against a persistent worker subprocess.

Out-of-process on purpose: in-process ``mypy.api.run`` leaks RSS (~5.6 MB/run) in a long-lived
server. But spawning a fresh ``python -m mypy -c`` *per call* reloads typeshed/build state every
time (~320 ms floor). So we keep ONE worker process alive (``mypy_worker.py``) calling ``api.run``
in a loop — typeshed stays resident, warm runs drop to ~60 ms — and bound the leak by recycling
that worker every ``_RECYCLE_AFTER_RUNS`` calls.

This is NOT the dmypy daemon. dmypy only supports ``--follow-imports`` ``normal``/``error`` and,
under ``normal``, never re-checks our synthetic ``-c`` probe (stale-verdict bug). ``api.run``
rebuilds the check each call, so valid→invalid→valid verdicts stay correct across the worker's
life (re-verified against that exact sequence).
"""

from __future__ import annotations

import atexit
import contextlib
import hashlib
import json
import logging
import os
import queue
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import cast

logger = logging.getLogger(__name__)

# Caps a hung mypy so a validation fails (fail-open upstream) instead of pinning a worker forever.
# 30 s covers a cold ~12 s cache build with margin; the old 120 s was ~260x a warm run.
_RUN_TIMEOUT_SECONDS = 30.0

# Recycle the worker after this many runs to bound the in-process RSS leak (~5.6 MB/run).
_RECYCLE_AFTER_RUNS = 100

# Grace period for a terminated worker to exit before we SIGKILL it.
_TERMINATE_GRACE_SECONDS = 5.0

# Sentinel a reader thread queues when its worker's stdout closes (worker died / was killed).
_EOF = object()


def _child_process_env() -> dict[str, str]:
    """Build the environment for the spawned mypy worker process."""
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
    """Type-checks code against a persistent `mypy_worker.py` process, recycled to bound RSS."""

    def __init__(self, flags: list[str], cache_key: str | None = None) -> None:
        self._flags = list(flags)
        self._cache_dir = _cache_dir(cache_key)
        # mypy has no cross-process cache locking, and one worker serves everyone: serialize runs.
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[str] | None = None
        self._queue: queue.Queue[object] | None = None
        self._reader: threading.Thread | None = None
        self._run_count = 0
        # close() only fires on a clean LSP shutdown; atexit covers hard kills / dropped stdio.
        atexit.register(self.close)

    def run(self, code: str) -> tuple[str, str, int]:
        """Type-check `code`, returning (stdout, stderr, exit_code); errors report as `<string>`."""
        with self._lock:
            if self._run_count >= _RECYCLE_AFTER_RUNS:
                self._kill_worker()
            self._ensure_worker()
            try:
                return self._exchange(code)
            except _WorkerTimeout:
                logger.warning("mypy worker timed out after %ss; killing it", _RUN_TIMEOUT_SECONDS)
                self._kill_worker()
                return "", "mypy timed out", 2
            except _WorkerDied as first:
                # Worker crashed mid-request: respawn once and retry before giving up.
                logger.warning("mypy worker died (%s); respawning and retrying once", first)
                self._kill_worker()
                self._ensure_worker()
                try:
                    return self._exchange(code)
                except (_WorkerDied, _WorkerTimeout) as second:
                    logger.warning("mypy worker failed again (%s); failing open", second)
                    self._kill_worker()
                    return "", str(second), 2

    def close(self) -> None:
        """Terminate the worker if running. Idempotent — safe to call repeatedly / at exit."""
        with self._lock:
            self._kill_worker()

    # --- internals (all callers hold self._lock) ---

    def _ensure_worker(self) -> None:
        """Spawn the worker if it is absent or has exited."""
        if self._proc is not None and self._proc.poll() is None:
            return
        cmd = [
            sys.executable,
            "-u",
            "-m",
            "fangtype.validation.mypy_worker",
            *self._flags,
            "--cache-dir",
            self._cache_dir,
        ]
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,  # avoid undrained-PIPE-fill deadlock; crashes come via JSON
            text=True,
            env=_child_process_env(),
        )
        self._run_count = 0
        self._queue = queue.Queue()
        self._reader = threading.Thread(
            target=self._reader_loop, args=(self._proc, self._queue), daemon=True
        )
        self._reader.start()

    @staticmethod
    def _reader_loop(proc: subprocess.Popen[str], out_queue: queue.Queue[object]) -> None:
        """Drain the worker's stdout onto its queue; queue a sentinel when stdout closes."""
        assert proc.stdout is not None
        for line in proc.stdout:
            out_queue.put(line)
        out_queue.put(_EOF)

    def _exchange(self, code: str) -> tuple[str, str, int]:
        """Send one request and read its response; raise on death/timeout for run() to handle."""
        assert self._proc is not None and self._proc.stdin is not None and self._queue is not None
        # Typed local: an inline literal passed to json.dumps's Any param infers as dict[Any, Any].
        payload = {"code": code}
        try:
            self._proc.stdin.write(json.dumps(payload) + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, ValueError, OSError) as e:  # worker gone before it read us
            raise _WorkerDied(str(e)) from e

        try:
            item = self._queue.get(timeout=_RUN_TIMEOUT_SECONDS)
        except queue.Empty:
            raise _WorkerTimeout from None
        if item is _EOF:
            raise _WorkerDied("worker exited without responding")

        self._run_count += 1
        response = cast("dict[str, str | int]", json.loads(cast("str", item)))
        return (
            cast("str", response["out"]),
            cast("str", response["err"]),
            cast("int", response["code"]),
        )

    def _kill_worker(self) -> None:
        """Terminate the worker and join its reader thread. Safe if none is running."""
        proc, reader = self._proc, self._reader
        self._proc = self._queue = self._reader = None
        self._run_count = 0
        if proc is None:
            return
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=_TERMINATE_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        # Close our pipe ends so the reader's `for line in stdout` ends and the thread can join.
        for stream in (proc.stdin, proc.stdout):
            if stream is not None:
                with contextlib.suppress(OSError):
                    stream.close()
        if reader is not None:
            reader.join(timeout=_TERMINATE_GRACE_SECONDS)


class _WorkerTimeout(Exception):
    """The worker did not respond within the per-request timeout."""


class _WorkerDied(Exception):
    """The worker process exited or its pipe broke mid-request."""
