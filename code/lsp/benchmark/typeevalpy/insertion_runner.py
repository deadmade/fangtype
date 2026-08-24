"""Measure the fangtype LSP server's insertion *yield* over the TypeEvalPy corpus."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING

from benchmark.lsp_client.factory import ClientBridge, map_over_bridge
from benchmark.lsp_client.shim import insert_all
from benchmark.typeevalpy import official
from benchmark.typeevalpy.fact_emitter import emit_facts, split_types
from benchmark.typeevalpy.inference_runner import enumerate_pairs

if TYPE_CHECKING:
    from pathlib import Path

TYPE_CATEGORIES: tuple[str, ...] = tuple(official.categorize_facts([]).keys())

_PROGRESS_EVERY = 25

FactKey = tuple[str | None, str | None, str]


@dataclass
class InsertionScore:
    """Aggregated insertion yield over a set of files."""

    tool_name: str
    file_count: int
    num_all: int  # inferred facts (yield denominator)
    num_caught_exact: int  # inserted AND type matches inferred (yield numerator)
    num_caught_partial: int  # inserted at all (annotation present, any type)
    per_category: dict[str, dict[str, int]]  # {cat: {"num_all", "num_caught_exact"}}
    sound_count: int  # files where every inferred fact was inserted with correct type
    modified_file_count: int  # files where the server actually produced an edit
    complete_count: int  # modified files whose post-insert source compiles cleanly
    out_root: Path | None = None

    @property
    def exact_pct(self) -> float:
        """Insertion yield percentage (0 when there are no inferred facts)."""
        return (self.num_caught_exact / self.num_all * 100) if self.num_all else 0.0


def _fact_key(fact: dict) -> FactKey:
    """Map an ``emit_facts`` fact dict to its (scope, name, kind) key.

    Mirrors the discriminator conventions of ``emit_facts``: ``parameter`` +
    ``function`` for params, ``variable`` (``self.x`` -> attribute) for locals/attrs,
    ``function`` alone for returns.
    """
    if "parameter" in fact:
        return (fact.get("function"), fact["parameter"], "param")
    if "variable" in fact:
        variable = fact["variable"]
        kind = "attribute" if variable.startswith("self.") else "variable"
        return (fact.get("function"), variable, kind)
    return (fact.get("function"), None, "return")


def _record_annassign(node: ast.AST, enclosing: str | None, out: dict[FactKey, str]) -> None:
    """Record an inserted variable/attribute annotation keyed by (scope, name, kind)."""
    if not isinstance(node, ast.AnnAssign):
        return
    target = node.target
    if isinstance(target, ast.Name):
        out[(enclosing, target.id, "variable")] = ast.unparse(node.annotation)
    elif isinstance(target, ast.Attribute):
        out[(enclosing, ast.unparse(target), "attribute")] = ast.unparse(node.annotation)


def inserted_types(modified_source: str) -> dict[FactKey, str]:
    """Map every annotation present in ``modified_source`` to its unparsed type string.

    Keyed by ``(enclosing-function-qname, name, kind)`` -- the same key space as
    ``_fact_key`` -- so lines shifted by declaration-style insertion don't matter.
    Returns an empty dict on ``SyntaxError`` (broken output -> whole-file miss).
    """
    try:
        tree = ast.parse(modified_source)
    except SyntaxError:
        return {}

    out: dict[FactKey, str] = {}

    def visit(node: ast.AST, prefix: str, enclosing_func: str | None) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                qname = f"{prefix}.{child.name}" if prefix else child.name
                if child.returns is not None:
                    out[(qname, None, "return")] = ast.unparse(child.returns)
                args = child.args
                for arg in args.posonlyargs + args.args + args.kwonlyargs:
                    if arg.annotation is not None:
                        out[(qname, arg.arg, "param")] = ast.unparse(arg.annotation)
                for extra in (args.vararg, args.kwarg):
                    if extra is not None and extra.annotation is not None:
                        out[(qname, extra.arg, "param")] = ast.unparse(extra.annotation)
                visit(child, qname, qname)
            elif isinstance(child, ast.ClassDef):
                qname = f"{prefix}.{child.name}" if prefix else child.name
                visit(child, qname, enclosing_func)
            else:
                _record_annassign(child, enclosing_func, out)
                visit(child, prefix, enclosing_func)

    visit(tree, "", None)
    return out


def _types_equal(inferred: list[str], inserted: str) -> bool:
    """Whether the inserted annotation carries the inferred type (order-insensitive)."""
    return set(split_types(inserted)) == set(inferred)


def classify_file(
    candidates: list[dict], modified_source: str | None
) -> tuple[list[dict], list[dict]]:
    """Split inferred ``candidates`` into (matched, inserted-any-type) for one file.

    ``matched`` = element annotated AND inserted type equals the inferred type.
    ``inserted`` (partial) = element annotated, any type -- a superset of ``matched``.
    ``modified_source is None`` (nothing inserted / server error) means every candidate
    is a miss.
    """
    if modified_source is None:
        return [], []
    present = inserted_types(modified_source)
    matched: list[dict] = []
    inserted: list[dict] = []
    for fact in candidates:
        key = _fact_key(fact)
        if key not in present:
            continue
        inserted.append(fact)
        if _types_equal(fact["type"], present[key]):
            matched.append(fact)
    return matched, inserted


def _bucket_counts(facts: list[dict]) -> dict[str, int]:
    """Per-category counts (``function_returns`` etc.) via the pure official bucketer."""
    categorized = official.categorize_facts(facts)
    return {cat: len(categorized[cat]) for cat in TYPE_CATEGORIES}


def _compiles(source: str) -> bool:
    """Whether the post-insert source compiles (parser + symbol table).

    Stronger than ``ast.parse``: also catches symbol-table errors like
    ``annotated name 'x' can't be nonlocal`` that a corrupt insertion can produce but
    that ``ast.parse`` silently accepts. ``ValueError`` guards null-byte sources.
    """
    try:
        compile(source, "<benchmark>", "exec")
        return True
    except (SyntaxError, ValueError):
        return False


@dataclass
class _FileInsertion:
    """One file's contribution to the aggregate insertion yield."""

    candidates: list[dict]
    matched: list[dict]
    inserted: list[dict]
    modified_ok: bool  # server produced an edit
    compiles: bool  # modified source compiles cleanly (only meaningful when modified_ok)


def _insert_one(bridge: ClientBridge, pair: tuple[Path, Path], _index: int) -> _FileInsertion:
    """Drive the server's real insert over one file and classify the result."""
    py_path, _gt_path = pair
    source = py_path.read_text()
    uri = py_path.resolve().as_uri()
    hints, preview = bridge.collect_sync(uri, source, did_open=False)
    candidates = emit_facts(source, hints, preview, filename=py_path.name)

    try:
        _ok, modified = bridge.run_sync(insert_all(bridge.client, uri))
    except Exception:
        modified = None

    matched, inserted = classify_file(candidates, modified)
    return _FileInsertion(
        candidates=candidates,
        matched=matched,
        inserted=inserted,
        modified_ok=modified is not None,
        compiles=modified is not None and _compiles(modified),
    )


def run_insertion_benchmark(
    engine: str = "jedi",
    *,
    benchmark_dir: Path | None = None,
    tool_name: str = "fangtype-insertion",
    show_progress: bool = True,
) -> InsertionScore:
    """Drive the LSP server's real insert over every file and aggregate insertion yield.

    Every file goes through one server process, in input order, which is the
    configuration the tool actually ships in. That is not a claim that the per-file yield
    is deterministic -- two runs have been measured to infer a different candidate set on
    some files (see ``sec:eval-threats`` in the thesis).
    """
    pairs = enumerate_pairs(benchmark_dir)
    if not pairs:
        msg = "No benchmark files found"
        raise ValueError(msg)

    num_all = 0
    num_caught_exact = 0
    num_caught_partial = 0
    per_category = {cat: {"num_all": 0, "num_caught_exact": 0} for cat in TYPE_CATEGORIES}
    sound_count = 0
    modified_file_count = 0
    complete_count = 0

    total = len(pairs)
    done = 0

    def report(_index: int, _pair: tuple[Path, Path], _result: _FileInsertion | None) -> None:
        nonlocal done
        done += 1
        if show_progress and done % _PROGRESS_EVERY == 0:
            print(f"Progress: [{done}/{total}] ({done / total * 100:.1f}%)")

    file_results = map_over_bridge(
        pairs,
        make_bridge=lambda: ClientBridge(engine=engine),
        fn=_insert_one,
        on_done=report,
    )

    for record in file_results:
        if record is None:
            continue
        num_all += len(record.candidates)
        num_caught_exact += len(record.matched)
        num_caught_partial += len(record.inserted)
        cand_cat = _bucket_counts(record.candidates)
        matched_cat = _bucket_counts(record.matched)
        for cat in TYPE_CATEGORIES:
            per_category[cat]["num_all"] += cand_cat[cat]
            per_category[cat]["num_caught_exact"] += matched_cat[cat]

        if record.candidates and len(record.matched) == len(record.candidates):
            sound_count += 1
        if record.modified_ok:
            modified_file_count += 1
            if record.compiles:
                complete_count += 1

    if show_progress:
        print(f"Progress: [{total}/{total}] (100.0%)")

    return InsertionScore(
        tool_name=tool_name,
        file_count=total,
        num_all=num_all,
        num_caught_exact=num_caught_exact,
        num_caught_partial=num_caught_partial,
        per_category=per_category,
        sound_count=sound_count,
        modified_file_count=modified_file_count,
        complete_count=complete_count,
        out_root=None,
    )
