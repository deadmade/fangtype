# Saved benchmark results

These are the existing evaluation results for Fangtype **0.5.15**, using
Jedi **0.20.0**, mypy **2.1.0**, and CPython **3.14.7**. They were copied from the
original evaluation artifacts; the benchmarks have not been rerun for this
public repository.

The [machine-readable summary](results/summary.json) is computed from the saved
data. Recompute it from the repository root with:

```bash
python benchmarks/summarize.py
```

The script checks toolchain pins, category totals, per-target results, and the
annotation census before printing the summary. It needs no third-party packages.

## TypeEvalPy

The inference benchmark covers **153 files and 850 reference annotations**.
An exact match means the inferred type matches the reference under the harness's
normalization and official TypeEvalPy scoring.

| Inference tool | Exact matches | Rate |
| --- | ---: | ---: |
| Fangtype | 635 / 850 | 74.7% |
| Jedi reference | 415 / 850 | 48.8% |

The Jedi row is the reference runner on the same pinned corpus and toolchain.
It is not a comparison against another editor or its full inference pipeline.

The insertion benchmark measures how many of **689 inferred candidates** reached
the source with their inferred type intact:

| Insertion configuration | Candidates written with the inferred type | Yield |
| --- | ---: | ---: |
| mypy gate on | 627 / 689 | 91.0% |
| mypy gate off | 660 / 689 | 95.8% |

This is insertion yield, not accuracy against the 850 reference annotations.
A candidate can be written faithfully even if inference produced the wrong type.
The saved data also records that all 145 modified files with the gate on and all
148 modified files with the gate off compiled successfully; compilation does
not establish type correctness.

## mypy corpus

The selected corpus contains **143 Python files**, including **134 files with
removable annotations**. Its independent AST census counts **17,290 annotations**:
**16,753** removable targets and **537 protected class-level declarations**.
Those protected declarations remain in the stripped corpus. The selection
excludes directories named `test` or `test-data`; it is not the entire mypy
checkout.

| Run | Exact matches to the original annotations | Rate |
| --- | ---: | ---: |
| Restoration, annotated cross-file context | 5,547 / 16,753 | 33.1% |
| Restoration, stripped cross-file context | 2,888 / 16,753 | 17.2% |
| Insertion, mypy gate on | 5,106 / 16,753 | 30.5% |
| Insertion, mypy gate off | 5,723 / 16,753 | 34.2% |

In the annotated-context restoration run, only the document under test is
stripped; imported modules still expose their annotations. In the stripped-context
run, also called cold start, cross-file resolution uses the prepared stripped
corpus. Here, cold start describes annotation availability, not cache state or
startup timing. Both runs score the same targets.

The insertion runs use the annotated cross-file context. They measure what
actually reached the edited file, scoring only annotations for which the corpus
provides a reference. Missing and failed targets stay in the denominator.
An exact match reproduces the author's type; a different type is not necessarily
invalid, but it does not count as an exact restoration. The lower exact-match
count with the gate enabled also shows that validation can reject candidates
that match the reference.

## Data and provenance

| Artifact | Contents |
| --- | --- |
| [typeevalpy_inference.json](results/typeevalpy_inference.json) | Fangtype inference results and category breakdowns |
| [typeevalpy_inference_jedi.json](results/typeevalpy_inference_jedi.json) | Jedi reference results |
| [typeevalpy_insertion.json](results/typeevalpy_insertion.json) | Insertion yield with validation |
| [typeevalpy_insertion_nogate.json](results/typeevalpy_insertion_nogate.json) | Insertion yield without validation |
| [mypy_restore.json.gz](results/mypy_restore.json.gz) | Restoration results with annotated cross-file context |
| [mypy_restore_coldstart.json.gz](results/mypy_restore_coldstart.json.gz) | Restoration results with stripped cross-file context |
| [mypy_insert.json.gz](results/mypy_insert.json.gz) | Per-target insertion results with validation |
| [mypy_insert_nogate.json.gz](results/mypy_insert_nogate.json.gz) | Per-target insertion results without validation |
| [mypy_annotation_census.json](results/mypy_annotation_census.json) | Annotation counts and protected declarations |
| [mypy_corpus_census.json](results/mypy_corpus_census.json) | Corpus selection and file counts |
| [versions.json](results/versions.json) | Toolchain and corpus revisions recorded by the original runs |
| [provenance.json](results/provenance.json) | Original and public source revisions, checksums, and path normalization |

The original source revision remains in the result metadata. Since the public
Git history was rewritten, its equivalent public revision is recorded separately
in `provenance.json`. These results describe that measured revision, rather than
an independently measured result for every subsequent commit.

Only machine-specific paths were changed: workspace and manifest paths became
repository-relative, and temporary output directories became
`<temporary-directory>`. All other values are preserved. Large JSON files use
gzip compression; the summary script reads both formats directly.

These saved results do not include a runtime benchmark, so they do not quantify
the speed limitations mentioned in the main README.
