# Fangtype

Interactive Python type annotation for VS Code. Fangtype infers types, displays
them as inlay hints, and writes annotations into your source when you accept
them. It uses Jedi for inference and mypy to check candidate annotations.

## Install

Build the extension using the steps below, then use **Extensions: Install from
VSIX…** in VS Code to install `fangtype.vsix`. Select a Python 3.12 or newer
interpreter through the Python extension. Fangtype's default `managed` mode
creates a dedicated environment for its server dependencies on first use.

See the [extension guide](code/vscode-extension/README.md) for settings,
commands, and debugging.

## Develop

The [Nix](https://nixos.org/) flake provides Python, Node, and development tools:

```bash
nix develop
```

`nix develop .#cli` selects the same shell. With direnv, `.envrc` loads it
automatically. The shell exports `PYTHONPATH=$PWD/code/lsp/src`.

Without Nix, use Python 3.12 or newer and Node 24:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e './code/lsp[dev]' nox pip-tools
```

Run server checks from `code/lsp`:

```bash
python -m pytest
ruff check src
mypy --config-file pyproject.toml .
```

Run extension checks and build a VSIX from `code/vscode-extension`:

```bash
npm ci
npm test
npm run lint
nox -s build_package
```

`nox -s build_package` bundles the server, builds the extension, and writes
`fangtype.vsix`. Built packages are ignored by Git. The tag-triggered GitHub
workflow also builds a VSIX and attaches it to a release.

## Repository layout

| Path | Contents |
| --- | --- |
| `code/lsp` | Python language server, tests, and benchmark tools |
| `code/vscode-extension` | VS Code client and packaging tools |
| `code/annotation-census` | Independent annotation census script |

## Benchmarks

The optional TypeEvalPy and mypy corpora are pinned Git submodules. Initialize
them only if you want to run the benchmarks:

```bash
git submodule update --init --recursive
cd code/lsp
python -m benchmark.run_benchmark --help
python -m benchmark.mypy_eval.census --help
```

The census script also provides help, run from the repository root:

```bash
python code/annotation-census/census_annotations.py --help
```

## License

[MIT](LICENSE). Benchmark corpora retain their respective upstream licenses.
