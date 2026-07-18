# Fangtype (VS Code extension)

Fangtype infers, validates, and inserts Python type annotations. This extension
launches the Fangtype language server and surfaces its results as inlay hints,
code actions, and diagnostics. The server itself lives in `code/lsp/`.

## First run

The VSIX is universal: it ships no native/compiled code, so the same package
works on any OS with a CPython 3.12, 3.13, or 3.14 interpreter.

By default (`fangtype.installMode: managed`) the extension creates a **dedicated
virtual environment** the first time it starts, installs the server's pinned
dependencies (mypy, jedi, libcst, …) into it, and launches the server from that
venv. This env lives under the extension's global storage — **your project and
global interpreters are never modified**, so there are no version conflicts and
no PEP 668 "externally-managed-environment" errors. A one-time progress
notification ("Creating Fangtype environment / Installing server dependencies")
shows while it builds; subsequent launches reuse it.

The venv is built from the interpreter you've selected (see resolution order
below) and keyed by that interpreter's CPython **minor** version, so switching
Python versions builds a fresh env rather than reusing an ABI-incompatible one.
Inference and validation stay **project-aware**: even though the server runs in
the isolated venv, Jedi and mypy are pointed at your project interpreter, so
imports of your project's third-party packages still resolve.

> **Debian/Ubuntu:** the managed venv needs the `venv` module. If your `python3`
> lacks it, the build fails with a clear prompt offering `sudo apt install
> python3-venv` (or switching to `fromEnvironment`).

If you'd rather install into your own selected interpreter instead, set
`fangtype.installMode` to `fromEnvironment` (see below). Run **Fangtype: Rebuild
Environment** to recreate the managed venv after corruption or a dependency bump.

## How the server is launched (from source, no binary)

The extension **runs the server from source under a Python interpreter** — there
is no PyInstaller binary. At launch it runs:

```
<interpreter> bundled/tool/lsp_server.py
```

`bundled/tool/lsp_server.py` is a small bootstrap: it arranges `sys.path` /
`PYTHONPATH` according to the import strategy, then hands off to
`fangtype.server.main`. The interpreter is resolved in this order:

1. the `fangtype.interpreter` setting (an argv array, e.g. `["/usr/bin/python"]`);
2. the interpreter selected via the **Python extension** (`ms-python.python`);
3. the `FANGTYPE_INTERPRETER` environment variable (escape hatch when
   `ms-python.python` is not installed).

If none resolves, the extension reports an error instead of launching.

### `fangtype.installMode`

Decides how the server's Python dependencies are provided:

| Mode              | Behavior                                                                                     |
| ----------------- | -------------------------------------------------------------------------------------------- |
| `managed` (default) | Build/own a dedicated venv under global storage; launch the server from it. Never touches your project/global env; inference stays project-aware. |
| `fromEnvironment` | Launch under the selected interpreter; if its deps are missing, offer to `pip install` them into that interpreter. Mutates the selected env. |
| `off`             | Don't manage or probe deps. Only valid together with `fangtype.path` (you run your own server). |

`fangtype.path` (below) is the full manual escape hatch and wins over
`installMode` entirely.

### `fangtype.importStrategy`

Only consulted under `installMode: fromEnvironment` (and `off`/`path`) — **ignored
under `managed`**, where the venv is the authoritative source of dependencies.
It decides where Python looks for the `fangtype` package and its dependencies:

| Strategy          | PYTHONPATH order                              | Use for                        |
| ----------------- | --------------------------------------------- | ------------------------------ |
| `useBundled`      | `bundled/libs` + `bundled/tool` **prepended** | shipping (self-contained VSIX) |
| `fromEnvironment` | bundled dirs **appended** (inherited wins)    | dev / tests / editable installs |

Under `fromEnvironment` the interpreter's own environment (or an inherited
`PYTHONPATH`) provides `fangtype` and its deps, so `bundled/libs` need not exist.

> **ABI caveat (`useBundled`):** `bundled/libs` contains native wheels (libcst
> and friends) compiled against **one CPython minor version**. A VSIX built for
> 3.14 will not import under a 3.13/3.15 interpreter. `useBundled` therefore
> couples the shipped bundle to the interpreter's minor version, and VSIXs are
> **per-platform** — currently `linux-x64`; other platforms are separate builds.

### Overrides

- `fangtype.interpreter` — argv for the interpreter to run the bootstrap under.
- `fangtype.path` — run an already-installed server **command directly**,
  bypassing the interpreter and the bootstrap script entirely.
- `fangtype.args` — extra arguments appended to the launch.

## Debugging (extension + Python server)

The repo's `.vscode/launch.json` ships three ways to debug from the editor:

- **Run Extension** — F5 launches an Extension Development Host with the
  extension loaded (no Python debugger).
- **Debug Extension + Python** (a compound) — the one to pick when you want to
  step through the **Python language server**. It:
  1. launches the Extension Development Host with `DEBUG_FANGTYPE=1` and
     `DEBUG_FANGTYPE_WAIT=1` in its environment, then
  2. attaches a `debugpy` client to `localhost:5678`.

When `DEBUG_FANGTYPE` is set in the launch environment, the extension runs the
debug entrypoint `bundled/tool/lsp_runner.py` (instead of `lsp_server.py`). That
runner starts a `debugpy` listener before booting the server; with
`DEBUG_FANGTYPE_WAIT` set it blocks until the debugger attaches, so the compound
works regardless of which side connects first. Set breakpoints anywhere in the
server sources (`code/lsp/src/fangtype/…`) and they will bind once the attach
connects.

`debugpy` must be importable by the interpreter running the server (it is a
dev-only dependency and is **not** shipped in `bundled/libs`). If it is missing,
`lsp_runner.py` prints a warning to stderr and boots normally — the server still
runs, it just can't be attached to.

### Debug env knobs

| Variable              | Default     | Effect                                          |
| --------------------- | ----------- | ----------------------------------------------- |
| `DEBUG_FANGTYPE`      | _(unset)_   | Any non-empty value runs `lsp_runner.py` and starts the listener. |
| `DEBUG_FANGTYPE_PORT` | `5678`      | Port the `debugpy` listener binds on `localhost`. |
| `DEBUG_FANGTYPE_WAIT` | _(unset)_   | Any non-empty value blocks the server until a debugger attaches. |

The `fangtype.path` override never switches to the debug runner (it runs its own
command directly).

## Building and packaging

Run these **inside `nix develop`** (the dev shell provides Node, Python 3.14, and
`vsce`; `nox` sessions use `venv_backend=none` and rely on that shell):

```bash
npm run build          # esbuild → dist/extension.cjs (fast dev build)
npm run lint           # eslint (src only)
npm run test           # pretest (build && package) then a real VS Code instance
nox -s setup           # pip-install deps + the fangtype package into bundled/libs
nox -s build_package   # full VSIX build (setup + build + vsce package)
npm run package        # vsce package on its own
```

`nox -s setup` is only needed to populate `bundled/libs` for a `useBundled`
shipping build; the integration tests launch the server from source with
`fromEnvironment` and do not require it.

## Tests

`npm run test` launches a real VS Code instance and runs the mocha suites in
`test/suite/`. The downloaded `@vscode/test-electron` binary runs directly under
the system's `nix-ld` (no `steam-run`/FHS wrapper needed); the dev shell exports
`NIX_LD_LIBRARY_PATH` with the VS Code runtime libs so its native `.so`s resolve.
The test workspace's `.vscode/settings.json`
(generated by `.vscode-test.mjs`) points `fangtype.interpreter` at the resolved
Python and sets `fangtype.importStrategy=fromEnvironment`, so the server is
launched from source under that interpreter — no bundled binary and no
`nox -s setup` required.
