# Fangtype

Interactive Python type annotation for VS Code. Fangtype infers types, displays
them as inlay hints, and writes annotations into your source when you accept
them. It uses Jedi for inference and mypy to check candidate annotations.

I built Fangtype as part of my studies at DHBW Heidenheim. I'm sharing the code
here, but I've chosen to keep the accompanying thesis private.

The project should work as provided, but it has known limitations. Unfortunately,
type inference can be slow and may miss many annotations. I'm not actively using
Python at the moment, so I don't currently plan further updates.

If you're interested in the project, feel free to fork it and build something
awesome with it. If you have any questions, just send me an email. :)

Cheers,
Dead

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

### Saved results

These are my saved **Fangtype 0.5.15** results, using Jedi 0.20.0, mypy 2.1.0,
and CPython 3.14.7. They have not been rerun for this public repository.

| Benchmark | Metric | Result |
| --- | --- | ---: |
| TypeEvalPy / Fangtype | Exact inference match | 635 / 850 (74.7%) |
| TypeEvalPy / Jedi reference | Exact inference match | 415 / 850 (48.8%) |
| TypeEvalPy / gate on | Insertion yield | 627 / 689 (91.0%) |
| TypeEvalPy / gate off | Insertion yield | 660 / 689 (95.8%) |
| mypy / annotated context | Exact restoration | 5,547 / 16,753 (33.1%) |
| mypy / stripped context | Exact restoration | 2,888 / 16,753 (17.2%) |
| mypy / gate on | Exact insertion match | 5,106 / 16,753 (30.5%) |
| mypy / gate off | Exact insertion match | 5,723 / 16,753 (34.2%) |

TypeEvalPy inference is scored against 850 reference annotations across 153
files. Its insertion yield measures how many of 689 inferred candidates were
written with their inferred type intact; it does not measure correctness against
the reference annotations.

The mypy runs score 16,753 removable annotations. In the annotated-context run,
imported modules still expose their annotations; the stripped-context run uses
the prepared stripped corpus for cross-file resolution. The insertion runs use
annotated cross-file context. These results show that matching the original
annotations remains difficult, particularly when other files are also stripped.

See the [benchmark report](benchmarks/README.md) for methodology, limitations,
and links to the [saved data](benchmarks/results). The large result files are
gzip-compressed; only local machine paths were normalized. Recompute the summary
without rerunning the benchmarks:

```bash
python benchmarks/summarize.py
```

### Run the benchmarks

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
