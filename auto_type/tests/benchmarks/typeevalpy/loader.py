"""Load TypeEvalPy benchmark data."""

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class AnnotationType(Enum):
    """Type of annotation in ground truth."""

    SIMPLE_VARIABLE = "simple_variable"  # x = 42
    COMPLEX_VARIABLE = "complex_variable"  # obj.attr, list[0]
    FUNCTION_RETURN = "function_return"  # def f() -> int
    FUNCTION_PARAM = "function_param"  # def f(a: int)
    OTHER = "other"


@dataclass
class BenchmarkCase:
    """Single annotation from ground truth."""

    file_path: Path  # Absolute path to .py file
    source_code: str  # Cached source code
    line_number: int  # 1-indexed (from JSON)
    col_offset: int  # 0-indexed (from JSON)
    variable_name: str | None  # For variables
    function_name: str | None  # For function returns
    parameter_name: str | None  # For parameters
    expected_types: list[str]  # Expected type(s) from JSON
    category: str  # e.g., "python_features/lists/simple"
    annotation_type: AnnotationType


def get_benchmark_dir() -> Path:
    """Get benchmark directory, ensuring it exists."""
    benchmark_dir = Path(__file__).parent.parent / "data" / "TypeEvalPy" / "micro-benchmark"

    if not benchmark_dir.exists():
        raise FileNotFoundError(
            f"TypeEvalPy benchmark not found at {benchmark_dir}\n\n"
            "Please clone it:\n"
            "  cd auto_type/tests/benchmarks/data\n"
            "  git clone https://github.com/secure-software-engineering/TypeEvalPy.git"
        )

    return benchmark_dir


def find_ground_truth_files(benchmark_dir: Path) -> list[Path]:
    """Find all *_gt.json files recursively."""
    return sorted(benchmark_dir.rglob("*_gt.json"))


def categorize_annotation(ann: dict[str, object]) -> AnnotationType:
    """Determine annotation type from JSON structure."""
    if "parameter" in ann:
        return AnnotationType.FUNCTION_PARAM
    elif "function" in ann:
        return AnnotationType.FUNCTION_RETURN
    elif "variable" in ann:
        var_name = ann["variable"]
        # Complex variables: obj.attr, items[0], etc.
        if "[" in var_name or "." in var_name:  # type: ignore[operator]
            return AnnotationType.COMPLEX_VARIABLE
        return AnnotationType.SIMPLE_VARIABLE
    return AnnotationType.OTHER


def extract_category_from_path(gt_file: Path) -> str:
    """Extract category from file path.

    Example: .../python_features/lists/simple/main_gt.json
             -> python_features/lists/simple
    """
    parts = gt_file.parts
    # Find index of 'micro-benchmark'
    try:
        idx = parts.index("micro-benchmark")
        # Category is everything between micro-benchmark and filename
        category_parts = parts[idx + 1 : -1]
        return "/".join(category_parts)
    except ValueError:
        return "unknown"


def load_benchmark_case(gt_file: Path, annotation: dict[str, object]) -> BenchmarkCase:
    """Convert JSON annotation to BenchmarkCase."""
    # Python file is in same directory as ground truth
    py_file = gt_file.parent / annotation["file"]  # type: ignore[operator]

    # Read source code (cached per file)
    try:
        source_code = py_file.read_text()
    except FileNotFoundError:
        source_code = ""  # Handle missing files gracefully

    # Extract category
    category = extract_category_from_path(gt_file)

    return BenchmarkCase(
        file_path=py_file,
        source_code=source_code,
        line_number=annotation["line_number"],  # type: ignore[arg-type]
        col_offset=annotation["col_offset"],  # type: ignore[arg-type]
        variable_name=annotation.get("variable"),  # type: ignore[arg-type]
        function_name=annotation.get("function"),  # type: ignore[arg-type]
        parameter_name=annotation.get("parameter"),  # type: ignore[arg-type]
        expected_types=annotation["type"],  # type: ignore[arg-type]
        category=category,
        annotation_type=categorize_annotation(annotation),
    )


def load_benchmark(benchmark_dir: Path | None = None) -> list[BenchmarkCase]:
    """Load all benchmark cases.

    Returns:
        List of all benchmark cases (typically ~845)
    """
    if benchmark_dir is None:
        benchmark_dir = get_benchmark_dir()

    cases = []
    gt_files = find_ground_truth_files(benchmark_dir)

    print(f"Found {len(gt_files)} ground truth files")

    for gt_file in gt_files:
        try:
            annotations = json.loads(gt_file.read_text())
            for ann in annotations:
                cases.append(load_benchmark_case(gt_file, ann))
        except json.JSONDecodeError:
            print(f"Warning: Failed to parse {gt_file}")
            continue
        except Exception as e:
            print(f"Warning: Error loading {gt_file}: {e}")
            continue

    return cases
