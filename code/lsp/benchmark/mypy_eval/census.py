"""Census the mypy checkout by the same rule that selects the evaluation corpus.

The restore manifest already records how many Python files the checkout holds and how
many of them the corpus keeps. It does not record where the difference went, so the
thesis cannot show a reader whether the selection rule dropped a rounding error or most
of the repository.

Every count here is derived from ``prepare``'s own constants and helpers rather than
from a second list of directory names. A census with its own copy of the exclusion rule
can drift from what ``prepare`` actually selects, and then the table it feeds describes a
corpus that was never built.

This is read-only over the checkout. It does not touch the prepared workspace, so running
it cannot invalidate an existing run's artefacts.

    python -m benchmark.mypy_eval.census --output benchmark/tmp/mypy_corpus_census.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from benchmark.mypy_eval.prepare import (
    _ALWAYS_EXCLUDED_DIRS,
    _DEFAULT_EXCLUDE_DIRS,
    _iter_python_files,
    get_mypy_dir,
    read_git_revision,
)

# The part name given to files sitting directly in the checkout root rather than in any
# directory, and to the two halves of the mypy package the selection rule splits.
ROOT_SCRIPTS = "root_scripts"
MYPY_PACKAGE = "mypy_package"
MYPY_TESTS = "mypy_tests"


def _part_of(path: Path, checkout_root: Path, mypy_dir: Path, kept: frozenset[Path]) -> str:
    """Name the part of the checkout a Python file belongs to.

    The mypy package splits in two, because the selection rule keeps the package and
    drops its tests. Membership of ``kept`` is what decides that split, so the split can
    never disagree with the corpus itself.
    """
    if path.is_relative_to(mypy_dir):
        return MYPY_PACKAGE if path in kept else MYPY_TESTS
    relative = path.relative_to(checkout_root)
    return ROOT_SCRIPTS if len(relative.parts) == 1 else relative.parts[0]


def census_checkout(mypy_dir: Path) -> dict[str, object]:
    """Count every Python file in the checkout, grouped by the part it sits in.

    ``mypy_dir`` points at the ``mypy/`` source package, so the checkout root is one
    level up and also holds ``mypyc/``, ``test-data/``, ``misc/``, ``docs/`` and a few
    loose scripts.
    """
    checkout_root = mypy_dir.parent
    kept = frozenset(_iter_python_files(mypy_dir))

    parts: Counter[str] = Counter()
    for path in checkout_root.rglob("*.py"):
        if _ALWAYS_EXCLUDED_DIRS.intersection(path.parts):
            continue
        parts[_part_of(path, checkout_root, mypy_dir, kept)] += 1

    return {
        "mypy_revision": read_git_revision(mypy_dir),
        "checkout_total_python_files": sum(parts.values()),
        "corpus_files": len(kept),
        "excluded_dirs": sorted(_DEFAULT_EXCLUDE_DIRS),
        "parts": dict(sorted(parts.items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Write the census JSON here")
    parser.add_argument(
        "--mypy-dir",
        type=Path,
        default=None,
        help="The mypy/ source package (defaults to the submodule under benchmark/data)",
    )
    args = parser.parse_args()

    census = census_checkout(get_mypy_dir(args.mypy_dir))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(census, indent=2) + "\n")

    parts = census["parts"]
    assert isinstance(parts, dict)
    for name, count in parts.items():
        print(f"{name:>16}  {count:>4}")
    print(f"{'total':>16}  {census['checkout_total_python_files']:>4}")
    print(f"{'corpus keeps':>16}  {census['corpus_files']:>4}")
    print(f"\nwrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
