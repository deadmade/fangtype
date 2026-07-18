"""Engine-agnostic per-document inference cache, hash-guarded and lock-free (event-loop only)."""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fangtype.inference.inference_result import InferenceResult

_CacheKey = tuple[str, int | None, int]


class DocumentCache:
    """Bounded LRU mapping a document identity to its raw ``InferenceResult``."""

    # Bounded on purpose: unbounded once regressed the mypy benchmark (resident scope trees).
    _MAX = 8

    def __init__(self) -> None:
        self._store: OrderedDict[_CacheKey, tuple[str, InferenceResult]] = OrderedDict()

    @staticmethod
    def hash_source(source: str) -> str:
        """Content hash used as the stale-result guard."""
        return hashlib.sha256(source.encode("utf-8")).hexdigest()

    def get(
        self, uri: str, version: int | None, generation: int, source: str
    ) -> InferenceResult | None:
        """Return the cached result, else ``None``; hit needs key+hash match, mismatch drops it."""
        key = (uri, version, generation)
        entry = self._store.get(key)
        if entry is None:
            return None

        stored_hash, result = entry
        if stored_hash != self.hash_source(source):
            del self._store[key]
            return None

        self._store.move_to_end(key)
        return result

    def put(
        self,
        uri: str,
        version: int | None,
        generation: int,
        source: str,
        result: InferenceResult,
    ) -> None:
        """Cache ``result`` for this document identity, evicting the LRU if over bound."""
        key = (uri, version, generation)
        self._store[key] = (self.hash_source(source), result)
        self._store.move_to_end(key)
        while len(self._store) > self._MAX:
            self._store.popitem(last=False)

    def evict(self, uri: str) -> None:
        """Drop every cached version/generation for one document (didChange/didClose)."""
        for key in [k for k in self._store if k[0] == uri]:
            del self._store[key]

    def clear(self) -> None:
        """Drop everything (test/reset helper)."""
        self._store.clear()
