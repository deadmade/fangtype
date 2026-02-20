"""Load TypeEvalPy benchmark data."""

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class AnnotationType(Enum):
    """Type of annotation in ground truth."""

    SIMPLE_VARIABLE = "simple_variable"  # x = 42
    COMPLEX_VARIABLE = "complex_variable"  # obj.attr, list[0] (legacy, use specific types below)
    SUBSCRIPT_ACCESS = "subscript_access"  # d['a'], list[0] - annotatable: value: Type = d['key']
    ATTRIBUTE_ACCESS = (
        "attribute_access"  # self.width, obj.attr - annotatable: self.attr: Type = value
    )
    ITERATION_VARIABLE = (
        "iteration_variable"  # for i in range(...) - annotatable: i: Type (pre-declaration)
    )
    FUNCTION_RETURN = "function_return"  # def f() -> int
    FUNCTION_PARAM = "function_param"  # def f(a: int)
    OTHER = "other"


def is_subscript_access(var_name: str) -> bool:
    """Check for subscript patterns: d['a'], list[0], data[0]['name'].

    These can be annotated: value: Type = d['key']
    """
    return "[" in var_name


def is_attribute_access(var_name: str) -> bool:
    """Check for attribute access patterns: self.width, obj.attr.

    These can be annotated: self.attr: Type = value
    """
    return "." in var_name


def is_iteration_variable(source_code: str, var_name: str, line_number: int) -> bool:
    """Check if variable is a loop iteration variable.

    For loop variables like 'for i in range(10)' can be annotated: i: int (pre-declaration).

    Args:
        source_code: The source code to check
        var_name: Variable name to check
        line_number: 1-indexed line number where variable is defined

    Returns:
        True if variable is a loop iteration variable
    """
    try:
        lines = source_code.splitlines()
        if line_number < 1 or line_number > len(lines):
            return False
        line = lines[line_number - 1].strip()
        # Check for 'for var_name in ...' pattern
        return line.startswith("for ") and f" {var_name} " in line.replace(",", " ")
    except Exception:
        return False


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
    project_root: Path | None = None  # Project root for Jedi import resolution


def get_benchmark_dir() -> Path:
    """Get benchmark directory, ensuring it exists."""
    benchmark_dir = Path(__file__).parent.parent / "data" / "TypeEvalPy" / "micro-benchmark"

    if not benchmark_dir.exists():
        raise FileNotFoundError(
            f"TypeEvalPy benchmark not found at {benchmark_dir}\n\n"
            "Please clone it:\n"
            "  cd auto_type/benchmark/data\n"
            "  git clone https://github.com/secure-software-engineering/TypeEvalPy.git"
        )

    return benchmark_dir


def find_ground_truth_files(benchmark_dir: Path) -> list[Path]:
    """Find all *_gt.json files recursively."""
    return sorted(benchmark_dir.rglob("*_gt.json"))


def categorize_annotation(ann: dict[str, object], source_code: str | None = None) -> AnnotationType:
    """Determine annotation type from JSON structure.

    Priority order:
    1. parameter - function parameter annotation
    2. variable - variable annotation (may have function context)
       - subscript access: d['a'], list[0] - NOT annotatable inline
       - attribute access: self.width, obj.attr - NOT annotatable inline
       - iteration variable: for i in range(...) - NOT annotatable inline
       - simple variable: x = 42
    3. function - function return type annotation

    Args:
        ann: Annotation dictionary from ground truth JSON
        source_code: Optional source code to check for iteration variables

    Returns:
        The appropriate AnnotationType for this annotation
    """
    if "parameter" in ann:
        return AnnotationType.FUNCTION_PARAM
    elif "variable" in ann:
        # Variable annotations take priority over function context
        # e.g., {"variable": "self.width", "function": "Rectangle.__init__"}
        # is a variable annotation, not a function return annotation
        var_name = str(ann["variable"])

        # Check for subscript access first (d['a'], list[0])
        if is_subscript_access(var_name):
            return AnnotationType.SUBSCRIPT_ACCESS

        # Check for attribute access (self.width, obj.attr)
        if is_attribute_access(var_name):
            return AnnotationType.ATTRIBUTE_ACCESS

        # Check for iteration variable (for i in range(...))
        if source_code is not None:
            line_num_raw = ann.get("line_number", 0)
            line_number = int(line_num_raw) if isinstance(line_num_raw, int | str) else 0
            if is_iteration_variable(source_code, var_name, line_number):
                return AnnotationType.ITERATION_VARIABLE

        return AnnotationType.SIMPLE_VARIABLE
    elif "function" in ann:
        return AnnotationType.FUNCTION_RETURN
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


def load_benchmark_case(
    gt_file: Path, annotation: dict[str, object], benchmark_dir: Path | None = None
) -> BenchmarkCase:
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

    # Determine project root for Jedi (use benchmark directory or find micro-benchmark parent)
    if benchmark_dir is not None:
        project_root = benchmark_dir
    else:
        # Try to find micro-benchmark directory in the path
        project_root = None
        try:
            parts = gt_file.parts
            if "micro-benchmark" in parts:
                idx = parts.index("micro-benchmark")
                project_root = Path(*parts[: idx + 1])
        except ValueError, IndexError:
            pass

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
        annotation_type=categorize_annotation(annotation, source_code),
        project_root=project_root,
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
                cases.append(load_benchmark_case(gt_file, ann, benchmark_dir))
        except json.JSONDecodeError:
            print(f"Warning: Failed to parse {gt_file}")
            continue
        except Exception as e:
            print(f"Warning: Error loading {gt_file}: {e}")
            continue

    return cases
