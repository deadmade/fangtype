"""CancellationToken — cooperative cancel flag polled from hot inference loops (no time budget)."""

from __future__ import annotations

import threading


class CancellationToken:
    """A thread-safe cooperative cancel flag."""

    def __init__(self) -> None:
        self._cancel = threading.Event()

    def cancelled(self) -> bool:
        """Return True once cancel() has been called. Cheap: poll freely."""
        return self._cancel.is_set()

    def cancel(self) -> None:
        """Request cancellation; hot loops bail at their next poll."""
        self._cancel.set()
