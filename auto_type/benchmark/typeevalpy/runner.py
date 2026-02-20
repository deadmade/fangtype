"""Run inference on benchmark cases and categorize results."""

import ast
import asyncio
import re
from dataclasses import dataclass
from enum import Enum

from auto_type.container import get_container
from auto_type.protocols import InferenceEngineProtocol, TypeAnnotationWorkflowProtocol
from benchmark.typeevalpy.expression_resolver import resolve_expression_type
from benchmark.typeevalpy.loader import AnnotationType, BenchmarkCase

# Pattern to match function signatures like "func()" or "func(a, b) -> int"
_FUNC_SIGNATURE_PATTERN = re.compile(r"^[a-zA-Z_]\w*\([^)]*\)(\s*->\s*.+)?$")


class ResultStatus(Enum):
    """Status of inference result."""

    CORRECT = "correct"  # ✅ Inferred correctly
    INCORRECT = "incorrect"  # ❌ Inferred wrong type
    UNSUPPORTED = "unsupported"  # ⚠️ Couldn't infer (returns None)
    OUT_OF_SCOPE = "out_of_scope"  # 🔵 Not a simple variable


@dataclass
class InferenceResult:
    """Result of running inference on one annotation."""

    case: BenchmarkCase
    status: ResultStatus
    inferred_type: str | None  # What we inferred (if any)
    reason: str | None  # Failure/skip reason


@dataclass
class BenchmarkResults:
    """Complete benchmark results."""

    total: int
    results: list[InferenceResult]

    @property
    def correct(self) -> list[InferenceResult]:
        """Get all correct inferences."""
        return [r for r in self.results if r.status == ResultStatus.CORRECT]

    @property
    def incorrect(self) -> list[InferenceResult]:
        """Get all incorrect inferences."""
        return [r for r in self.results if r.status == ResultStatus.INCORRECT]

    @property
    def unsupported(self) -> list[InferenceResult]:
        """Get all unsupported cases."""
        return [r for r in self.results if r.status == ResultStatus.UNSUPPORTED]

    @property
    def out_of_scope(self) -> list[InferenceResult]:
        """Get all out-of-scope cases."""
        return [r for r in self.results if r.status == ResultStatus.OUT_OF_SCOPE]


def _extract_base_type(type_str: str) -> str | None:
    """Extract base type from generic type.

    Args:
        type_str: Type string that may be generic

    Returns:
        Base type if generic, None otherwise

    Examples:
        >>> _extract_base_type("list[str]")
        "list"
        >>> _extract_base_type("dict[str, int]")
        "dict"
        >>> _extract_base_type("list[list[int]]")
        "list"
        >>> _extract_base_type("int")
        None
    """
    if "[" in type_str:
        return type_str.split("[")[0]
    return None


def _parse_union_components(type_str: str) -> set[str]:
    """Parse union type into its components.

    Handles both modern (X | Y) and old-style (Union[X, Y]) syntax.
    Recursively extracts all union members and deduplicates.

    Args:
        type_str: Type string that may be a union

    Returns:
        Set of unique type components

    Examples:
        >>> _parse_union_components("int | str")
        {"int", "str"}
        >>> _parse_union_components("Union[int, str]")
        {"int", "str"}
        >>> _parse_union_components("Union[str, str, str]")
        {"str"}
        >>> _parse_union_components("int")
        {"int"}
    """
    type_str = type_str.strip()

    if "|" in type_str and not type_str.startswith("Union["):
        parts = [part.strip() for part in type_str.split("|")]
        return set(parts)

    if type_str.startswith("Union[") and type_str.endswith("]"):
        inner = type_str[6:-1]

        components = []
        current = ""
        bracket_depth = 0

        for char in inner:
            if char == "[":
                bracket_depth += 1
                current += char
            elif char == "]":
                bracket_depth -= 1
                current += char
            elif char == "," and bracket_depth == 0:
                if current.strip():
                    components.append(current.strip())
                current = ""
            else:
                current += char

        if current.strip():
            components.append(current.strip())

        result = set()
        for comp in components:
            result.update(_parse_union_components(comp))

        return result

    return {type_str}


def _normalize_none_type(type_str: str) -> str:
    """Normalize None/NoneType/Nonetype to lowercase 'none' for comparison."""
    if type_str.lower() in ("none", "nonetype"):
        return "none"
    return type_str


def _canonical_type_tags(type_str: str) -> set[str]:
    """Return narrow canonical tags for semantically equivalent benchmark types."""
    tags = {type_str}
    normalized = type_str.strip()
    if not normalized:
        return tags

    if normalized in ("Generator", "generator"):
        tags.add("generator")

    itertools_equivalents = {
        "Iterator[tuple]": {
            "itertools.groupby",
            "itertools.permutations",
            "itertools.combinations",
            "itertools.product",
            "zip",
        },
        "Iterator[int]": {"itertools.count"},
        "Iterator[str]": {"itertools.repeat", "itertools.compress"},
        "Iterator": {"map"},
        "cycle": {"itertools.cycle"},
        "chain": {"itertools.chain"},
        "itertools.cycle": {"cycle"},
        "itertools.chain": {"chain"},
    }
    tags.update(itertools_equivalents.get(normalized, set()))

    # Imported qualified names are equivalent to their simple class/type names.
    if "." in normalized:
        tags.add(normalized.split(".")[-1])

    return tags


def type_matches(inferred: str, expected: list[str]) -> bool:
    """Check if inferred type matches any expected type.

    Supports bidirectional generic type matching for improved flexibility.

    Handles:
    - Exact matches: "int" == "int"
    - Forward generic matches: "list" == "list[int]"
    - Reverse generic matches: "list[str]" == "list"
    - Union matches (order-independent):
        - "Union[int, str]" matches ["str", "int"]
        - "int | str" matches ["str", "int"]
        - "Union[str, str, str]" matches ["str"] (deduplicates)
    - Callable matches: function names match "callable"

    Examples:
        >>> type_matches("int", ["int"])
        True
        >>> type_matches("int | None", ["int"])
        True
        >>> type_matches("Union[int, str]", ["str", "int"])
        True
        >>> type_matches("Union[str, str, str]", ["str"])
        True
        >>> type_matches("list", ["list[int]"])
        True
        >>> type_matches("list[str]", ["list"])
        True
    """
    if inferred in expected:
        return True

    inferred_tags = _canonical_type_tags(inferred)
    expected_tags: set[str] = set()
    for exp in expected:
        expected_tags.update(_canonical_type_tags(exp))
    if inferred_tags & expected_tags:
        return True

    expects_callable = any(exp.lower() == "callable" for exp in expected)
    if expects_callable and inferred.lower() == "callable":
        return True

    if any(exp.startswith(inferred + "[") for exp in expected):
        return True

    base_type = _extract_base_type(inferred)
    if base_type and base_type in expected:
        return True

    if "|" in inferred or "Union[" in inferred:
        inferred_components = _parse_union_components(inferred)

        if len(inferred_components) == 1:
            single_type = inferred_components.pop()
            if single_type in expected:
                return True
            single_base = _extract_base_type(single_type)
            if single_base and single_base in expected:
                return True
            return any(exp.startswith(single_type + "[") for exp in expected)

        expected_set = set(expected)

        if inferred_components == expected_set:
            return True

        if inferred_components.issubset(expected_set):
            return True

        if any(comp in expected_set for comp in inferred_components):
            return True

        for comp in inferred_components:
            if any(exp.startswith(comp + "[") for exp in expected):
                return True
            comp_base = _extract_base_type(comp)
            if comp_base and comp_base in expected_set:
                return True

    # Handle Type[X] matching "type"
    if inferred.startswith("Type[") and "type" in expected:
        return True

    # Handle NoneType/None/Nonetype case-insensitive matching
    normalized_inferred = _normalize_none_type(inferred)
    for exp in expected:
        if _normalize_none_type(exp) == normalized_inferred:
            return True

    # Handle callable matching - function signatures like "func() -> int"
    if expects_callable:
        normalized = inferred.lower()
        if "functiontype" in normalized or normalized in ("function", "builtins.function"):
            return True
        # Jedi often formats lambdas as "<lambda>(x) -> int"
        if inferred.startswith("<lambda>"):
            return True
        # Check if inferred looks like a function signature
        if _FUNC_SIGNATURE_PATTERN.match(inferred):
            return True
        # Also match simple function names (original behavior)
        if inferred and inferred[0].islower() and all(c.isalnum() or c == "_" for c in inferred):
            return True
    return False


def classify_unsupported_pattern(node: ast.expr) -> str:
    """Classify unsupported pattern (simple, based on AST node type)."""
    match node:
        case ast.Call():
            return "function_call"
        case ast.BinOp():
            return "binary_operation"
        case ast.UnaryOp():
            return "unary_operation"
        case ast.Subscript():
            return "subscript"
        case ast.Attribute():
            return "attribute_access"
        case ast.IfExp():
            return "conditional_expression"
        case ast.Compare():
            return "comparison"
        case ast.BoolOp():
            return "boolean_operation"
        case ast.Lambda():
            return "lambda"
        case ast.GeneratorExp():
            return "generator_expression"
        case _:
            return f"unknown_pattern_{type(node).__name__}"


def _get_function_by_qualified_name(
    tree: ast.Module, qualified_name: str
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Find a function by qualified name (e.g., 'outer.inner', 'Class.method').

    Args:
        tree: AST module to search
        qualified_name: Dot-separated qualified function name

    Returns:
        The function AST node if found, None otherwise
    """
    parts = qualified_name.split(".")

    if len(parts) == 1:
        # Simple function name - search at module level
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == parts[0]:
                return node
        return None

    # Qualified name - need to walk nested structure
    # Find the outermost container first
    current_nodes: list[ast.AST] = [tree]

    for i, part in enumerate(parts):
        next_nodes: list[ast.AST] = []
        found = False

        for current in current_nodes:
            if isinstance(current, ast.Module):
                # Search module body
                for node in current.body:
                    if (
                        isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
                        and node.name == part
                    ):
                        if i == len(parts) - 1:
                            # Last part - should be a function
                            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                                return node
                        else:
                            next_nodes.append(node)
                            found = True
            elif isinstance(current, ast.ClassDef):
                # Search class body
                for node in current.body:
                    if (
                        isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
                        and node.name == part
                    ):
                        if i == len(parts) - 1:
                            return node
                        else:
                            next_nodes.append(node)
                            found = True
            elif isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef):
                # Search function body for nested functions
                for node in current.body:
                    if (
                        isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
                        and node.name == part
                    ):
                        if i == len(parts) - 1:
                            return node
                        else:
                            next_nodes.append(node)
                            found = True

        if not found:
            return None
        current_nodes = next_nodes

    return None


def _find_parameter_in_function(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef, param_name: str
) -> ast.arg | None:
    """Find a parameter in a function by name, checking all parameter types.

    Args:
        func_node: Function AST node
        param_name: Name of the parameter to find

    Returns:
        The parameter AST node if found, None otherwise
    """
    args = func_node.args

    # Check regular positional/keyword args
    for arg in args.args:
        if arg.arg == param_name:
            return arg

    # Check positional-only args (Python 3.8+)
    for arg in args.posonlyargs:
        if arg.arg == param_name:
            return arg

    # Check vararg (*args)
    if args.vararg and args.vararg.arg == param_name:
        return args.vararg

    # Check kwarg (**kwargs)
    if args.kwarg and args.kwarg.arg == param_name:
        return args.kwarg

    # Check keyword-only args
    for arg in args.kwonlyargs:
        if arg.arg == param_name:
            return arg

    return None


def _find_assignment_for_variable(
    tree: ast.Module, var_name: str, line_number: int
) -> ast.Assign | ast.AnnAssign | None:
    """Find an assignment for a variable, searching by name and line range.

    Args:
        tree: AST module to search
        var_name: Name of the variable
        line_number: Expected line number (1-based)

    Returns:
        The assignment AST node if found, None otherwise
    """
    # Search for assignments at or near the given line
    # Allow some flexibility in line matching (±5 lines)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            # Check if this assignment defines the variable
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == var_name:
                    # Check line number with some tolerance
                    if abs(node.lineno - line_number) <= 5:
                        return node
                elif isinstance(target, ast.Tuple | ast.List):
                    # Handle tuple unpacking: a, b = 1, 2
                    for elt in target.elts:
                        if (
                            isinstance(elt, ast.Name)
                            and elt.id == var_name
                            and abs(node.lineno - line_number) <= 5
                        ):
                            return node
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == var_name
            and abs(node.lineno - line_number) <= 5
        ):
            # Handle annotated assignments: x: int = 5
            return node

    return None


def analyze_failure(case: BenchmarkCase) -> str:
    """Determine why inference failed by analyzing AST."""
    try:
        tree = ast.parse(case.source_code)

        # Handle different annotation types
        match case.annotation_type:
            case AnnotationType.SIMPLE_VARIABLE:
                # Find the assignment for this variable
                if case.variable_name:
                    assignment = _find_assignment_for_variable(
                        tree, case.variable_name, case.line_number
                    )
                    if assignment and (
                        isinstance(assignment, ast.Assign)
                        or (isinstance(assignment, ast.AnnAssign) and assignment.value)
                    ):
                        return classify_unsupported_pattern(assignment.value)

                # Fallback: try to find by exact line match
                for node in ast.walk(tree):
                    if isinstance(node, ast.Assign) and node.lineno == case.line_number:
                        return classify_unsupported_pattern(node.value)

                return "assignment_not_found"

            case AnnotationType.FUNCTION_PARAM:
                if not case.function_name or not case.parameter_name:
                    return "parameter_not_found"

                # Find function by qualified name
                func_node = _get_function_by_qualified_name(tree, case.function_name)
                if func_node:
                    # Find parameter in the function
                    param = _find_parameter_in_function(func_node, case.parameter_name)
                    if param:
                        if not param.annotation:
                            return "parameter_no_annotation"
                        return "parameter_inference_failed"

                return "parameter_not_found"

            case AnnotationType.FUNCTION_RETURN:
                if not case.function_name:
                    return "function_not_found"

                # Find function by qualified name
                func_node = _get_function_by_qualified_name(tree, case.function_name)
                if func_node:
                    # Check return statements
                    return_visitor = _ReturnStatementCollector()
                    return_visitor.visit(func_node)

                    if not return_visitor.returns:
                        return "no_return_statement"

                    # Check what kind of return values we have
                    for ret in return_visitor.returns:
                        if ret.value:
                            return classify_unsupported_pattern(ret.value)

                    return "return_type_unknown"

                return "function_not_found"

            case AnnotationType.COMPLEX_VARIABLE:
                # For complex variables (subscripts, attributes), try to find the pattern
                # This is tricky because we need to find the exact node at col_offset
                # For now, return a generic classification
                return "complex_variable_pattern"

            case AnnotationType.OTHER:
                return "other_annotation_type"

            case AnnotationType.ITERATION_VARIABLE:
                return "iteration_variable"

            case AnnotationType.ATTRIBUTE_ACCESS:
                return "attribute_access"

            case AnnotationType.SUBSCRIPT_ACCESS:
                return "subscript_access"

    except SyntaxError:
        return "syntax_error"
    except Exception as e:
        return f"analysis_failed: {type(e).__name__}"


class _ReturnStatementCollector(ast.NodeVisitor):
    """Collect all return statements in a function."""

    def __init__(self) -> None:
        """Initialize collector."""
        self.returns: list[ast.Return] = []

    def visit_Return(self, node: ast.Return) -> None:
        """Visit return statement."""
        if node.value:  # Skip bare 'return' statements
            self.returns.append(node)


async def run_inference_on_case(
    case: BenchmarkCase,
    workflow: TypeAnnotationWorkflowProtocol,
    inference_engine: InferenceEngineProtocol,
) -> InferenceResult:
    """Run inference on single case and categorize result.

    Uses the same TypeAnnotationWorkflow as the LSP server
    to ensure consistent behavior.

    Args:
        case: The benchmark case to process
        workflow: The workflow instance (cached from outer loop)
        inference_engine: The inference engine instance (cached from outer loop)
    """
    # Pass project_root from benchmark case for proper Jedi import resolution
    project_root = str(case.project_root) if case.project_root else None
    inference_result, _, _ = await workflow.infer_and_collect_types(
        case.source_code, str(case.file_path), project_root=project_root
    )

    # Query type based on annotation type
    inferred_type: str | None = None

    match case.annotation_type:
        case AnnotationType.SIMPLE_VARIABLE:
            # Simple variable: x = 42
            if case.variable_name is None:
                return InferenceResult(
                    case=case,
                    status=ResultStatus.UNSUPPORTED,
                    inferred_type=None,
                    reason="variable_name_missing",
                )

            # Query type at specific line number (flow-sensitive lookup)
            # Convert 1-based line number (from JSON) to 0-based (internal)
            # Use scope_tree.get_variable_type_at_line() to search all scopes
            type_info = inference_result.scope_tree.get_variable_type_at_line(
                case.variable_name, case.line_number - 1
            )
            if type_info and type_info.type_str != "Unknown":
                inferred_type = type_info.type_str

        case AnnotationType.FUNCTION_RETURN:
            # Function return type: def f() -> int
            if case.function_name is None:
                return InferenceResult(
                    case=case,
                    status=ResultStatus.UNSUPPORTED,
                    inferred_type=None,
                    reason="function_name_missing",
                )

            # Find function scope by qualified name (e.g., "MyClass.method")
            func_scope = inference_result.scope_tree.get_function_scope_by_qualified_name(
                case.function_name
            )

            if (
                func_scope
                and func_scope.return_type
                and func_scope.return_type.type_str != "Unknown"
            ):
                inferred_type = func_scope.return_type.type_str

        case AnnotationType.FUNCTION_PARAM:
            # Function parameter type: def f(a: int)
            if case.function_name is None or case.parameter_name is None:
                return InferenceResult(
                    case=case,
                    status=ResultStatus.UNSUPPORTED,
                    inferred_type=None,
                    reason="function_or_parameter_name_missing",
                )

            # Find function scope by qualified name (e.g., "MyClass.method")
            func_scope = inference_result.scope_tree.get_function_scope_by_qualified_name(
                case.function_name
            )

            if func_scope and case.parameter_name in func_scope.parameters:
                param_type = func_scope.parameters[case.parameter_name]
                if param_type.type_str != "Unknown":
                    inferred_type = param_type.type_str

        case AnnotationType.COMPLEX_VARIABLE:
            # Complex variables: obj.attr, list[0], dict['key'], etc.
            # Use infer_expression_type() which handles subscripts correctly
            if case.variable_name is None:
                return InferenceResult(
                    case=case,
                    status=ResultStatus.UNSUPPORTED,
                    inferred_type=None,
                    reason="variable_name_missing",
                )

            inferred_type = resolve_expression_type(case, inference_result)
            if inferred_type is None:
                try:
                    inferred_type = inference_engine.infer_expression_type(
                        case.source_code,
                        case.variable_name,
                        path=str(case.file_path),
                        line_hint=case.line_number,
                    )
                except Exception as e:
                    return InferenceResult(
                        case=case,
                        status=ResultStatus.UNSUPPORTED,
                        inferred_type=None,
                        reason=f"complex_variable_error: {e}",
                    )

        case AnnotationType.SUBSCRIPT_ACCESS:
            # Subscript access: value = d['key']
            # Use infer_expression_type() which handles subscripts correctly
            if case.variable_name is None:
                return InferenceResult(
                    case=case,
                    status=ResultStatus.UNSUPPORTED,
                    inferred_type=None,
                    reason="variable_name_missing",
                )

            inferred_type = resolve_expression_type(case, inference_result)
            if inferred_type is None:
                try:
                    inferred_type = inference_engine.infer_expression_type(
                        case.source_code,
                        case.variable_name,
                        path=str(case.file_path),
                        line_hint=case.line_number,
                    )
                except Exception as e:
                    return InferenceResult(
                        case=case,
                        status=ResultStatus.UNSUPPORTED,
                        inferred_type=None,
                        reason=f"subscript_access_error: {e}",
                    )

        case AnnotationType.ATTRIBUTE_ACCESS:
            # Attribute access: self.value = 100
            # Use infer_expression_type() which handles attributes correctly
            if case.variable_name is None:
                return InferenceResult(
                    case=case,
                    status=ResultStatus.UNSUPPORTED,
                    inferred_type=None,
                    reason="variable_name_missing",
                )

            inferred_type = resolve_expression_type(case, inference_result)
            if inferred_type is None:
                try:
                    inferred_type = inference_engine.infer_expression_type(
                        case.source_code,
                        case.variable_name,
                        path=str(case.file_path),
                        line_hint=case.line_number,
                    )
                except Exception as e:
                    return InferenceResult(
                        case=case,
                        status=ResultStatus.UNSUPPORTED,
                        inferred_type=None,
                        reason=f"attribute_access_error: {e}",
                    )

        case AnnotationType.ITERATION_VARIABLE:
            # Iteration variable: for i in range(10)
            # Query type at specific line number for the iteration variable
            if case.variable_name is None:
                return InferenceResult(
                    case=case,
                    status=ResultStatus.UNSUPPORTED,
                    inferred_type=None,
                    reason="variable_name_missing",
                )

            # Query type at specific line number
            type_info = inference_result.scope_tree.get_variable_type_at_line(
                case.variable_name, case.line_number - 1
            )
            if type_info and type_info.type_str != "Unknown":
                inferred_type = type_info.type_str

        case AnnotationType.OTHER:
            # Other patterns - truly not implemented
            return InferenceResult(
                case=case,
                status=ResultStatus.UNSUPPORTED,
                inferred_type=None,
                reason="other_annotation_type",
            )

    # Check if we inferred something
    if inferred_type is None:
        # Analyze WHY it wasn't inferred
        reason = analyze_failure(case)
        return InferenceResult(
            case=case, status=ResultStatus.UNSUPPORTED, inferred_type=None, reason=reason
        )

    # We inferred something - is it correct?
    if type_matches(inferred_type, case.expected_types):
        return InferenceResult(
            case=case, status=ResultStatus.CORRECT, inferred_type=inferred_type, reason=None
        )
    else:
        return InferenceResult(
            case=case,
            status=ResultStatus.INCORRECT,
            inferred_type=inferred_type,
            reason=f"Expected {case.expected_types}",
        )


async def _run_benchmark_async(
    cases: list[BenchmarkCase],
    show_progress: bool = True,
    max_concurrency: int = 10,
) -> BenchmarkResults:
    """Run inference on all cases asynchronously with a single event loop.

    Uses the DI container to get workflow and inference engine instances once,
    then reuses them for all cases to minimize overhead.
    Processes cases with limited concurrency to avoid overwhelming the system.

    Args:
        cases: List of benchmark cases to process
        show_progress: Whether to show progress indicators
        max_concurrency: Maximum number of concurrent inferences (default: 10)
    """
    # Get workflow and inference engine from DI container once (cached)
    container = get_container()
    workflow = container.get(TypeAnnotationWorkflowProtocol)
    inference_engine = container.get(InferenceEngineProtocol)

    total = len(cases)
    results: list[InferenceResult] = []
    completed = 0

    # Semaphore to limit concurrent inferences
    semaphore = asyncio.Semaphore(max_concurrency)

    async def process_case(case: BenchmarkCase) -> InferenceResult:
        """Process a single case with semaphore-controlled concurrency."""
        nonlocal completed
        async with semaphore:
            result = await run_inference_on_case(case, workflow, inference_engine)
            completed += 1
            if show_progress and completed % 50 == 0:
                print(f"Progress: [{completed}/{total}] ({completed / total * 100:.1f}%)")
            return result

    # Create tasks for all cases and run concurrently
    tasks = [process_case(case) for case in cases]
    results = await asyncio.gather(*tasks)

    if show_progress:
        print(f"Progress: [{total}/{total}] (100.0%)")

    return BenchmarkResults(total=total, results=list(results))


def run_benchmark(
    cases: list[BenchmarkCase],
    show_progress: bool = True,
) -> BenchmarkResults:
    """Run inference on all cases with progress indicator.

    Uses a single event loop for all cases to minimize asyncio overhead.
    DI container lookups are cached outside the loop.
    """
    import asyncio

    return asyncio.run(_run_benchmark_async(cases, show_progress))
