"""Unit tests for the document-level inference cache: cast sentinels + identity assertions."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from fangtype.utils.document_cache import DocumentCache

if TYPE_CHECKING:
    from fangtype.inference.inference_result import InferenceResult

URI = "file:///tmp/x.py"
SRC = "def add(a, b):\n    return a + b\n"


def _result(tag: str) -> InferenceResult:
    """A unique sentinel standing in for an InferenceResult."""
    return cast("InferenceResult", tag)


def test_hit_on_identical_identity() -> None:
    cache = DocumentCache()
    result = _result("r1")
    cache.put(URI, 1, 0, SRC, result)
    assert cache.get(URI, 1, 0, SRC) is result


def test_version_miss() -> None:
    cache = DocumentCache()
    cache.put(URI, 1, 0, SRC, _result("r1"))
    # Same uri/source/generation, newer version -> miss.
    assert cache.get(URI, 2, 0, SRC) is None


def test_hash_guard_miss_drops_stale_entry() -> None:
    """Matching key but mismatched content misses; stale result never served again after revert."""
    cache = DocumentCache()
    stale = _result("stale")
    cache.put(URI, 1, 0, SRC, stale)

    # Same (uri, version, generation) but the buffer content changed -> miss.
    assert cache.get(URI, 1, 0, SRC + "\n# edit\n") is None

    # The stale entry was dropped: the original source is no longer a hit either.
    assert cache.get(URI, 1, 0, SRC) is None


def test_settings_generation_miss() -> None:
    cache = DocumentCache()
    cache.put(URI, 1, 0, SRC, _result("r1"))
    # A bumped settings generation invalidates the entry.
    assert cache.get(URI, 1, 1, SRC) is None


def test_version_none_is_cacheable() -> None:
    """version=None (disk-backed reads) is a real key, not a bypass."""
    cache = DocumentCache()
    result = _result("r1")
    cache.put(URI, None, 0, SRC, result)
    assert cache.get(URI, None, 0, SRC) is result


def test_lru_bound_evicts_oldest() -> None:
    cache = DocumentCache()
    # Insert one more than the bound, all distinct uris.
    for i in range(DocumentCache._MAX + 1):
        cache.put(f"file:///f{i}.py", 1, 0, SRC, _result(f"r{i}"))

    assert len(cache._store) == DocumentCache._MAX
    # The oldest (f0) was evicted; the newest survive.
    assert cache.get("file:///f0.py", 1, 0, SRC) is None
    assert cache.get(f"file:///f{DocumentCache._MAX}.py", 1, 0, SRC) is not None


def test_get_promotes_recency() -> None:
    cache = DocumentCache()
    for i in range(DocumentCache._MAX):
        cache.put(f"file:///f{i}.py", 1, 0, SRC, _result(f"r{i}"))

    # Touch the oldest so it is no longer the eviction victim.
    assert cache.get("file:///f0.py", 1, 0, SRC) is not None
    # Insert a new entry -> the now-oldest (f1) is evicted, f0 survives.
    cache.put("file:///new.py", 1, 0, SRC, _result("new"))

    assert cache.get("file:///f0.py", 1, 0, SRC) is not None
    assert cache.get("file:///f1.py", 1, 0, SRC) is None


def test_evict_removes_all_versions_for_uri_only() -> None:
    cache = DocumentCache()
    cache.put(URI, 1, 0, SRC, _result("v1"))
    cache.put(URI, 2, 0, SRC, _result("v2"))
    cache.put(URI, 1, 1, SRC, _result("gen1"))
    other = "file:///other.py"
    cache.put(other, 1, 0, SRC, _result("other"))

    cache.evict(URI)

    assert cache.get(URI, 1, 0, SRC) is None
    assert cache.get(URI, 2, 0, SRC) is None
    assert cache.get(URI, 1, 1, SRC) is None
    # A different document is untouched.
    assert cache.get(other, 1, 0, SRC) is not None
