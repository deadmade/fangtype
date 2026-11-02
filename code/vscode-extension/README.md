# Fangtype for VS Code

Fangtype shows inferred Python types as inlay hints. Accept hints or use code
actions to insert annotations; use its commands to insert or remove annotations
at the cursor or throughout a file. Candidate insertions are checked with mypy
when `fangtype.mypyEnabled` is enabled.

## First run

Install the VSIX and select a Python 3.12 or newer interpreter with the Microsoft
Python extension. The VSIX bundles the pure Python Fangtype server; third-party
dependencies are installed separately.

By default, `fangtype.installMode` is `managed`. Fangtype creates a dedicated
virtual environment under the extension's global storage and installs its
pinned server dependencies there. It uses your selected project interpreter
for project-aware inference and validation. First use needs network access to
install dependencies. On Debian/Ubuntu, the interpreter may need the
`python3-venv` package.

## Settings

| Setting | Purpose |
| --- | --- |
| `fangtype.interpreter` | Interpreter argv array; defaults to the Python extension's selection, then `FANGTYPE_INTERPRETER`. |
| `fangtype.installMode` | `managed` (default), `fromEnvironment`, or `useBundled`. |
| `fangtype.mypyEnabled` | Enable mypy diagnostics and validation of candidate annotations. |
| `fangtype.crossFileContractsEnabled` | Enable inference from cross-file function contracts. |
| `fangtype.logLevel` | Server logging level; defaults to `warning`. |
| `fangtype.requestTimeoutSeconds` | Client timeout for insert/remove/preview requests; defaults to 120. |

`fromEnvironment` launches under the selected interpreter and offers to install
missing dependencies into it. This modifies that environment. An editable
Fangtype install in that environment takes precedence over the bundled server.

`useBundled` prioritizes the bundled Fangtype server under the selected
interpreter. Its third-party dependencies must still be available; only the
pure Python Fangtype package is bundled.

Run **Fangtype: Rebuild Environment** to recreate a managed environment, or
**Fangtype: Restart Language Server** after configuration changes.

## Commands

- **Fangtype: Insert Type Annotation at Cursor** (`Alt+Enter`)
- **Fangtype: Insert All Type Annotations in File**
- **Fangtype: Remove Type Annotation at Cursor**
- **Fangtype: Remove All Type Annotations in File**

## Build and test

Enter `nix develop` at the repository root, then run from this directory:

```bash
npm ci
npm test                # typecheck and unit tests using a VS Code stub
npm run lint
npm run build           # extension bundle only
nox -s setup            # bundle Fangtype and copy the dependency lockfile
nox -s build_package    # setup, build, and package fangtype.vsix
```

Without Nix, install Python development dependencies as described in the
[root README](../../README.md). The unit tests run under Node without an
Electron host. Python server tests live in `code/lsp/tests`.

## Debug

Open the repository root in VS Code. **Run Extension** starts an Extension
Development Host. **Debug Extension + Python** also attaches a Python debugger
to the server on `localhost:5678`; install `debugpy` in the server interpreter
first.

The debug runner recognizes `DEBUG_FANGTYPE`, `DEBUG_FANGTYPE_WAIT`, and
`DEBUG_FANGTYPE_PORT` (default `5678`). The compound launch configuration sets
the first two so the server waits for the debugger to attach.
