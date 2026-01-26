# Insertion Benchmark

This benchmark validates the **InsertionEngine** by testing the complete pipeline:
1. **JediInferenceEngine** infers types from Python code
2. **InsertionEngine** inserts type annotations
3. **Validator** checks correctness (syntax + semantics)

## Quick Start

```bash
# Run the full insertion benchmark
cd auto_type
uv run python tests/benchmarks/run_insertion_benchmark.py

# Filter to specific category
uv run python tests/benchmarks/run_insertion_benchmark.py --category lists

# Limit cases for quick testing
uv run python tests/benchmarks/run_insertion_benchmark.py --max-cases 100

# Export results to JSON
uv run python tests/benchmarks/run_insertion_benchmark.py --output results.json

# Export failures for debugging
uv run python tests/benchmarks/run_insertion_benchmark.py --export-failures failures/
```

## What It Tests

### Tested Cases
- ✅ Simple variable assignments (`x = 42`)
- ✅ All TypeEvalPy categories that use simple variables
- ✅ Various Python types (int, str, list, dict, etc.)

### Not Tested (Out of Scope)
- ❌ Complex variables (`obj.attr`, `list[0]`)
- ❌ Function parameters and return types
- ❌ Already annotated variables

### Validation Levels

1. **Syntactic Correctness**: Inserted code must parse without syntax errors
2. **Semantic Correctness**: Inserted type must match ground truth
3. **Annotation Presence**: Annotation must actually exist in modified code

## Results Interpretation

### Status Categories

| Status | Description | Example |
|--------|-------------|---------|
| ✅ **Correct** | Type inferred, inserted, and matches ground truth | `x = 42` → `x: int = 42` |
| ❌ **Type Mismatch** | Inserted but wrong type from inference | Inferred `float` but expected `int` |
| ⚠️ **Inference Failed** | JediInferenceEngine couldn't infer type | Complex expression |
| 💥 **Insertion Failed** | InsertionEngine failed to insert | Tuple unpacking, chained assignment |
| 🔍 **Syntax Error** | Inserted code has syntax errors | Invalid type string |
| 📝 **Annotation Missing** | Annotation not found in result | Bug in InsertionEngine |

### Metrics

**End-to-end Success Rate**: Percentage of cases where the entire pipeline succeeded
- Current: **~63%** (244/387 cases)

**Pipeline Breakdown**:
- Inference Success: **~82%** (316/387 cases)
- Insertion Success (given inference): **~86%** (273/316 cases)

## Architecture

```
auto_type/tests/benchmarks/
├── run_insertion_benchmark.py    # CLI entry point
├── insertion/
│   ├── loader.py                 # Filter insertable cases from TypeEvalPy
│   ├── validator.py              # Validate syntax and semantics
│   ├── runner.py                 # Run infer → insert workflow
│   └── reporter.py               # Generate reports and export JSON
└── typeevalpy/                   # Shared TypeEvalPy loader
```

## Benchmark Data

**Source**: TypeEvalPy micro-benchmark dataset

**Total annotations in TypeEvalPy**: 4,000+

**Insertable cases** (simple variables only): **387 cases**

**Categories tested**:
- `python_features/*`: Lists, dicts, assignments, builtins, etc.
- `analysis_sensitivities/*`: Field sensitivity, object sensitivity, etc.

## Example Output

```
============================================================
TypeEvalPy Insertion Benchmark
============================================================

Loading benchmark cases...
✓ Loaded 387 insertable cases

Running insertion benchmark...
Progress: [387/387] (100.0%)

============================================================
# Insertion Benchmark Report

## Summary

| Metric | Count | Percentage |
|--------|-------|------------|
| Total cases | 387 | 100.0% |
| ✅ Correct insertions | 244 | 63.0% |
| ❌ Type mismatches | 29 | 7.5% |
| ⚠️ Inference failures | 71 | 18.3% |
| 💥 Insertion failures | 43 | 11.1% |
| 🔍 Syntax errors | 0 | 0.0% |
| 📝 Annotation missing | 0 | 0.0% |

### Pipeline Success Rates

| Stage | Success Rate |
|-------|-------------|
| Inference (Jedi) | 316/387 (81.7%) |
| Insertion (given inference) | 273/316 (86.4%) |
| End-to-end | 244/387 (63.0%) |
```

## Common Failure Patterns

### Insertion Failures
- **Chained assignments**: `a = b = func()` (not supported by InsertionEngine)
- **Tuple unpacking**: `a, b = (1, 2)` (not simple variable)
- **Generator expressions**: `x = (i for i in range(10))` (complex pattern)

### Type Mismatches
- **NoneType inferences**: Jedi sometimes infers `NoneType` incorrectly
- **Generic vs specific**: Jedi infers `list` but ground truth expects `list[int]`
- **Callable types**: Function names vs generic `callable`

## Testing

Unit tests are in `tests/test_insertion_benchmark.py`:

```bash
cd auto_type
uv run pytest tests/test_insertion_benchmark.py -v
```

Tests cover:
- Loader: Case filtering and annotation detection
- Validator: Syntax validation, type matching, annotation verification
- Runner: End-to-end insertion workflow

## Comparison with Inference Benchmark

| Aspect | Inference Benchmark | Insertion Benchmark |
|--------|-------------------|-------------------|
| **Engines** | JediInferenceEngine | Jedi + InsertionEngine |
| **Scope** | All annotation types | Simple variables only |
| **Output** | Type strings | Modified source code |
| **Validation** | Type accuracy | Syntax + semantics |
| **Cases** | 4,000+ | 387 |
| **Purpose** | Measure inference quality | Validate insertion correctness |

## Future Improvements

1. **Function annotations**: Add support for parameter and return type insertions
2. **Bulk insertion**: Test `insert_types_bulk()` method
3. **Format preservation**: Measure how well comments/whitespace are preserved
4. **Error recovery**: Test insertion on partially invalid code
5. **Performance**: Add timing metrics for inference and insertion stages

## Contributing

To add new validation checks or improve the benchmark:

1. Edit modules in `tests/benchmarks/insertion/`
2. Add tests to `tests/test_insertion_benchmark.py`
3. Run tests: `uv run pytest tests/test_insertion_benchmark.py -v`
4. Run full benchmark: `uv run python tests/benchmarks/run_insertion_benchmark.py`
