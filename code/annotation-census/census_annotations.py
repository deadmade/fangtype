"""Count the annotations the mypy evaluation corpus holds.

The restore run reports a rate over 16753 targets. That number is what the removal engine
was willing to strip, not what the corpus contains, and nothing committed recorded the
difference. Without an independent total a rate over those targets cannot be read as a rate
over the corpus.

This counts the corpus on its own terms. ``ast`` is used rather than LibCST, because the
removal engine is built on LibCST and a count sharing its parser would not be independent of
the thing it is meant to give a denominator for. The counts were cross-checked against parso,
which agreed exactly on all four categories.

The engine declines one case. A bare ``x: int`` whose immediately enclosing scope is a class
may be a dataclass, TypedDict or NamedTuple field, so deleting the line would remove a member
rather than a type claim, and ``removal/engine.py:172`` skips it. Counting that case here
gives the corpus total its two parts, namely what removal reaches and what it declines.

Re-implementing that rule is only as good as the reading behind it, so ``--stripped`` checks
it against the corpus the engine actually wrote. That directory is a benchmark artefact rather
than a committed one, and the check is skipped when it is absent.

Read-only. It reads the corpus checkout and writes only the JSON file named by ``--output``.

    python census_annotations.py
    python census_annotations.py --output ../../thesis/evaluation/data/mypy_annotation_census.json
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import cast

# The corpus-selection rule, mirrored from benchmark/mypy_eval/prepare.py:32-33. A
# directory named `test` or `test-data` anywhere in the path drops the file, which is what
# keeps the corpus to the mypy package rather than its test suite.
ALWAYS_EXCLUDED_DIRS = frozenset({"__pycache__", ".git"})
DEFAULT_EXCLUDE_DIRS = frozenset({"test", "test-data"})


@dataclass
class AstCounts:
    """Annotation sites found by walking the syntax tree.

    The four categories are the ones the restore table reports, namely FR, FP, LV and AT.
    An annotated assignment counts as AT when its target is an attribute such as
    ``self.x: int``, and as LV otherwise. That is the same test the removal engine applies
    at ``removal/engine.py:120``, so the two classifications cannot diverge.
    """

    function_returns: int = 0
    function_parameters: int = 0
    local_variables: int = 0
    attributes: int = 0

    @property
    def annotation_sites(self) -> int:
        """Every position in the corpus that carries a written annotation."""
        return (
            self.function_returns
            + self.function_parameters
            + self.local_variables
            + self.attributes
        )


@dataclass
class CensusResult:
    """What one pass over a tree of files found."""

    counts: AstCounts = field(default_factory=AstCounts)
    declined: AstCounts = field(default_factory=AstCounts)
    unparsable: list[str] = field(default_factory=list)


def iter_corpus_files(package_root: Path) -> list[Path]:
    """Select the corpus files by the rule ``prepare`` uses, so the sets cannot diverge.

    Only ``*.py`` is taken. The checkout also vendors ``*.pyi`` stubs under ``typeshed/``,
    and those are not source the evaluation ever strips, so counting them would inflate
    the count with annotations that were never in scope.
    """
    skip = ALWAYS_EXCLUDED_DIRS | DEFAULT_EXCLUDE_DIRS
    return sorted(
        p for p in package_root.rglob("*.py") if not skip.intersection(p.parts)
    )


def _count_signatures(tree: ast.Module, counts: AstCounts) -> None:
    """Add the module's annotated parameters and returns to ``counts``.

    A flat walk is enough here, because every function node is visited exactly once
    however deeply it nests.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if node.returns is not None:
            counts.function_returns += 1

        args = node.args
        slots = [*args.posonlyargs, *args.args, *args.kwonlyargs]
        slots += [a for a in (args.vararg, args.kwarg) if a is not None]
        counts.function_parameters += sum(1 for a in slots if a.annotation is not None)


def _count_ann_assign(tree: ast.Module, counts: AstCounts) -> None:
    """Split the module's annotated assignments into attributes and everything else.

    An ``ast.Attribute`` target is the ``self.x: int`` case the restore table calls AT. A
    target of any other shape is LV.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.AnnAssign):
            continue
        if isinstance(node.target, ast.Attribute):
            counts.attributes += 1
        else:
            counts.local_variables += 1


def _count_declined(node: ast.AST, scope: str, declined: AstCounts) -> None:
    """Categorise the bare declarations the removal engine refuses to delete.

    The engine tests its innermost binding scope alone (``removal/engine.py:172``), so a
    declaration inside a method of a class does not qualify and one directly in the class
    body does. This descends by hand rather than using ``ast.walk``, because the enclosing
    scope is exactly what a flat walk throws away.

    The LV and AT split is applied rather than assumed. Every one of these is LV on the
    corpus as it stands, but ``Foo.x: int`` written in a class body would be AT.
    """
    for child in ast.iter_child_nodes(node):
        if (
            isinstance(child, ast.AnnAssign)
            and child.value is None
            and scope == "class"
        ):
            if isinstance(child.target, ast.Attribute):
                declined.attributes += 1
            else:
                declined.local_variables += 1

        if isinstance(child, ast.ClassDef):
            _count_declined(child, "class", declined)
        elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            _count_declined(child, "function", declined)
        else:
            _count_declined(child, scope, declined)


def count_tree(files: list[Path]) -> CensusResult:
    """Walk every file once, returning the counts and the files that would not parse."""
    result = CensusResult()
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            result.unparsable.append(str(path))
            continue
        _count_signatures(tree, result.counts)
        _count_ann_assign(tree, result.counts)
        _count_declined(tree, "module", result.declined)
    return result


def _git(root: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
        )
    except FileNotFoundError:
        return None
    return completed.stdout.strip() or None


def read_git_revision(root: Path) -> str | None:
    """The checked-out revision of the corpus, so a count can be tied to what it counted.

    ``git`` walks upwards, so pointing this at a directory that is not itself a checkout
    answers with the revision of whatever repository encloses it. For a copy of the corpus
    under ``benchmark/tmp`` that is this repository's own HEAD, which says nothing about
    which mypy was counted. Reporting nothing is better than reporting that.
    """
    corpus_repo = _git(root, "rev-parse", "--show-toplevel")
    if corpus_repo is None:
        return None
    if corpus_repo == _git(
        Path(__file__).resolve().parent, "rev-parse", "--show-toplevel"
    ):
        return None
    return _git(root, "rev-parse", "HEAD")


def build_report(package_root: Path, stripped_root: Path | None) -> dict[str, object]:
    """Count the corpus, and check the skip rule against the stripped tree when it exists."""
    files = iter_corpus_files(package_root)
    corpus = count_tree(files)

    total = corpus.counts.annotation_sites
    skipped = corpus.declined.annotation_sites
    report: dict[str, object] = {
        "corpus_root": str(package_root),
        "mypy_revision": read_git_revision(package_root),
        "corpus_files": len(files),
        "unparsable_files": corpus.unparsable,
        "annotation_total": total,
        "skipped_declarations": skipped,
        "removable": total - skipped,
        "by_category": asdict(corpus.counts),
        "declined_by_category": asdict(corpus.declined),
        "stripped_verified": False,
    }

    if stripped_root is None or not stripped_root.is_dir():
        return report

    # The stripped tree is what the engine itself wrote, so counting it checks the rule
    # above rather than restating it. Category by category, not only on the total.
    residue = count_tree(iter_corpus_files(stripped_root))
    report["stripped_root"] = str(stripped_root)
    report["stripped_remaining"] = residue.counts.annotation_sites
    report["stripped_by_category"] = asdict(residue.counts)
    report["stripped_verified"] = (
        asdict(residue.counts) == asdict(corpus.declined)
        and asdict(residue.declined) == asdict(corpus.declined)
        and not residue.unparsable
    )
    return report


def _category_lines(counts: dict[str, int]) -> list[str]:
    return [
        f"  FR  function return    {counts['function_returns']:>7}",
        f"  FP  function parameter {counts['function_parameters']:>7}",
        f"  LV  local variable     {counts['local_variables']:>7}",
        f"  AT  attribute          {counts['attributes']:>7}",
    ]


def _counts(report: dict[str, object], key: str) -> dict[str, int]:
    """Narrow one counts block, which the report widens to ``object`` on the way in."""
    return cast("dict[str, int]", report[key])


def _render(report: dict[str, object]) -> str:
    """Format the report as the table a reader can check the JSON against."""
    lines = [
        f"corpus     {report['corpus_root']}",
        f"revision   {report['mypy_revision'] or 'unknown'}",
        f"files      {report['corpus_files']}",
    ]
    if report["unparsable_files"]:
        count = len(cast("list[str]", report["unparsable_files"]))
        lines.append(f"UNPARSABLE {count} file(s), counts are incomplete")

    lines.append("")
    lines.append("annotation sites in the corpus")
    lines += _category_lines(_counts(report, "by_category"))
    lines.append(f"  {'-' * 30}")
    lines.append(f"  total{report['annotation_total']:>24}")
    lines.append("")
    lines.append("what removal does with them")
    lines.append(f"  reached{report['removable']:>22}")
    lines.append(
        f"  declined{report['skipped_declarations']:>21}"
        "   bare declaration in a class body"
    )

    lines.append("")
    if "stripped_remaining" in report:
        lines.append(f"checked against the stripped tree at {report['stripped_root']}")
        lines += _category_lines(_counts(report, "stripped_by_category"))
        lines.append(f"  {'-' * 30}")
        lines.append(f"  left{report['stripped_remaining']:>25}")
        verdict = "agrees" if report["stripped_verified"] else "DISAGREES"
        lines.append(f"  {verdict} with the declined count above")
    else:
        lines.append("no stripped tree found, so the declined count is unchecked")
    return "\n".join(lines)


def _payload(report: dict[str, object]) -> dict[str, object]:
    """The report minus the absolute paths, which are local to whoever ran the census.

    ``mypy_revision`` is what ties the count to what it counted, and it travels. The
    sibling artefact ``mypy_corpus_census.json`` commits a revision and no path for the
    same reason.
    """
    return {k: v for k, v in report.items() if not k.endswith("_root")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    here = Path(__file__).resolve().parent
    benchmark = here.parent / "lsp" / "benchmark"
    parser.add_argument(
        "--corpus",
        type=Path,
        default=benchmark / "data" / "mypy" / "mypy",
        help="The mypy/ source package the evaluation corpus is drawn from",
    )
    parser.add_argument(
        "--stripped",
        type=Path,
        default=benchmark / "tmp" / "mypy_eval" / "stripped",
        help="The corpus after the removal engine ran, used to check the skip rule",
    )
    parser.add_argument(
        "--output", type=Path, default=None, help="Write the report JSON here"
    )
    args = parser.parse_args()

    corpus = args.corpus.resolve()
    if not corpus.is_dir():
        print(f"corpus not found at {corpus}", file=sys.stderr)
        print("run `git submodule update --init` first", file=sys.stderr)
        return 2

    report = build_report(corpus, args.stripped.resolve() if args.stripped else None)
    print(_render(report))

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(_payload(report), indent=2) + "\n", encoding="utf-8"
        )
        print(f"\nwrote {args.output}")

    if report["unparsable_files"]:
        return 1
    if "stripped_remaining" in report and not report["stripped_verified"]:
        print("\nthe skip rule disagrees with the stripped tree", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
