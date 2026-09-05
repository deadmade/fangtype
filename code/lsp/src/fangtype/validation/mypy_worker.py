"""Long-lived mypy worker: `api.run` in a loop so typeshed stays parsed in RAM.

Spawned by `MypyRunner` as a persistent subprocess. Reads newline-delimited JSON requests
(`{"code": <str>}`) on stdin and writes newline-delimited JSON responses
(`{"out": str, "err": str, "code": int}`) on stdout, one per request, until stdin EOF.

Why a persistent process: a fresh `python -m mypy -c` reloads typeshed/build state every call
(~320ms floor); keeping one process alive drops warm runs to ~60ms. `api.run` rebuilds the check
each call, so — unlike the dmypy daemon — it does NOT go stale across valid/invalid probes. The
in-process RSS leak is bounded by the parent recycling this worker every N runs.

The fixed mypy flags + `--cache-dir <dir>` arrive as argv; only `code` varies per request.
"""

from __future__ import annotations

import json
import sys
import traceback
from typing import TextIO, cast


def main() -> int:
    """Serve `api.run` requests over stdio until stdin closes."""
    from mypy import api  # imported once; the whole point is to keep it resident

    # This project types `sys.stdin`/`sys.stdout` as `TextIO | Any`; cast once so the stream
    # operations below don't each trip disallow_any_expr.
    stdin = cast("TextIO", sys.stdin)
    stdout = cast("TextIO", sys.stdout)
    base_args = sys.argv[1:]

    # readline() (not `for line in stdin`) so each request is served as soon as it arrives,
    # without stdin readahead buffering holding a line back on a pipe.
    while True:
        raw = stdin.readline()
        if not raw:  # EOF: parent closed our stdin
            break
        request = raw.strip()
        if not request:
            continue
        code = cast("dict[str, str]", json.loads(request))["code"]
        response: dict[str, object]
        try:
            out, err, exit_code = api.run([*base_args, "-c", code])
            response = {"out": out, "err": err, "code": exit_code}
        except Exception:  # a bad request must not kill the worker; report via the normal channel
            response = {"out": "", "err": traceback.format_exc(), "code": 2}
        stdout.write(json.dumps(response) + "\n")
        stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
