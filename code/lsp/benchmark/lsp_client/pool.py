"""Run a benchmark over a pool of LSP bridges (one server subprocess per worker).

Every benchmark mode is an embarrassingly-parallel map: each corpus file drives an
independent LSP round-trip and produces a per-file result. Spawning N ``ClientBridge``
instances is safe by construction -- ``build_container()`` returns a fresh injector per
server process and all caches/temp files are per-process -- so this helper simply shards
the work list across ``workers`` persistent bridges.

Results are collected by input index, so a parallel run is byte-identical to the
sequential one: parallelism only changes wall-clock, never a reported score.
"""

from __future__ import annotations

import os
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from benchmark.lsp_client.factory import ClientBridge

_WORKER_CAP = 8


def resolve_workers(requested: int | None) -> int:
    """Resolve the worker count: honour an explicit ``requested`` value, else
    ``min(_WORKER_CAP, cpu_count // 2)`` (at least 1).

    ``workers == 1`` is a valid request and reproduces the exact sequential path
    (a single bridge, no thread pool) -- keep it as a debugging fallback.
    """
    if requested is not None and requested > 0:
        return requested
    return max(1, min(_WORKER_CAP, (os.cpu_count() or 2)))


def map_over_bridges[T, R](
    items: Sequence[T],
    *,
    make_bridge: Callable[[], ClientBridge],
    workers: int,
    fn: Callable[[ClientBridge, T, int], R],
    on_done: Callable[[int, T, R], None] | None = None,
) -> list[R | None]:
    """Map ``fn`` over ``items`` across a pool of ``workers`` LSP bridges.

    ``make_bridge`` builds one fresh ``ClientBridge`` (its own server subprocess). Each
    task borrows a bridge from the pool, calls ``fn(bridge, item, index)``, and returns
    the bridge for reuse -- dynamic borrowing load-balances heavy files instead of
    statically chunking. Results are placed by input index, so the returned list has the
    same order as ``items`` regardless of completion order.

    ``on_done(index, item, result)`` is invoked under a lock as each item finishes --
    use it for progress counters and journal appends (both need serialization). A worker
    of 1 runs everything on a single bridge in input order with no executor.
    """
    n = len(items)
    results: list[R | None] = [None] * n
    if n == 0:
        return results

    workers = max(1, min(workers, n))
    done_lock = threading.Lock()

    if workers == 1:
        bridge = make_bridge()
        try:
            for index, item in enumerate(items):
                result = fn(bridge, item, index)
                results[index] = result
                if on_done is not None:
                    on_done(index, item, result)
        finally:
            bridge.close()
        return results

    pool: queue.Queue[ClientBridge] = queue.Queue()
    bridges = [make_bridge() for _ in range(workers)]
    for bridge in bridges:
        pool.put(bridge)

    def _work(index: int, item: T) -> None:
        bridge = pool.get()
        try:
            result = fn(bridge, item, index)
        finally:
            pool.put(bridge)
        results[index] = result
        if on_done is not None:
            with done_lock:
                on_done(index, item, result)

    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(_work, i, item) for i, item in enumerate(items)]
            for future in futures:
                future.result()
    finally:
        for bridge in bridges:
            bridge.close()

    return results
