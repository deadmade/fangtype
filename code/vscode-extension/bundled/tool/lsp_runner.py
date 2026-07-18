"""Optional debug entrypoint for the Fangtype language server.

Identical to ``lsp_server.py`` except that, when ``DEBUG_FANGTYPE`` is set, it
starts a ``debugpy`` listener before booting the server so a debugger can attach.
``debugpy`` is a dev-only dependency and is never shipped in ``bundled/libs``;
if it is missing, this falls back to a normal launch.

Env knobs:
    DEBUG_FANGTYPE       Any non-empty value enables the listener.
    DEBUG_FANGTYPE_PORT  Listen port (default ``5678``).
    DEBUG_FANGTYPE_WAIT  Any non-empty value blocks until a client attaches.
"""

from __future__ import annotations

import os
import sys


def _maybe_start_debugpy() -> None:
    """Start a ``debugpy`` listener when ``DEBUG_FANGTYPE`` is set.

    All diagnostics go to stderr; stdout is reserved for the LSP framing and must
    never be written to here.
    """
    if not os.getenv("DEBUG_FANGTYPE"):
        return
    try:
        import debugpy
    except ImportError:
        print(
            "DEBUG_FANGTYPE set but debugpy is not installed; continuing.",
            file=sys.stderr,
        )
        return
    port = int(os.getenv("DEBUG_FANGTYPE_PORT", "5678"))
    debugpy.listen(("localhost", port))
    print(f"debugpy listening on localhost:{port}", file=sys.stderr)
    if os.getenv("DEBUG_FANGTYPE_WAIT"):
        debugpy.wait_for_client()


_maybe_start_debugpy()

# Importing lsp_server runs the sys.path / PYTHONPATH bootstrap as a side effect;
# we then hand off to the same server entrypoint it exposes.
import lsp_server  # noqa: E402,F401  (side effect: path/env bootstrap)

from fangtype.server import main  # noqa: E402

if __name__ == "__main__":
    main()
