"""Run inference on benchmark cases and categorize results."""

import ast
import re
from dataclasses import dataclass
from enum import Enum

from auto_type.container import get_container
from auto_type.protocols import InferenceEngineProtocol, TypeAnnotationWorkflowProtocol
from tests.benchmarks.typeevalpy.loader import AnnotationType, BenchmarkCase

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
    if "callable" in expected:
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


def analyze_failure(case: BenchmarkCase) -> str:
    """Determine why inference failed by analyzing AST."""
    try:
        tree = ast.parse(case.source_code)

        # Handle different annotation types
        match case.annotation_type:
            case AnnotationType.SIMPLE_VARIABLE:
                # Find the assignment at the given line
                for node in ast.walk(tree):
                    if isinstance(node, ast.Assign) and node.lineno == case.line_number:
                        # Found the assignment - classify what it is
                        return classify_unsupported_pattern(node.value)
                return "assignment_not_found"

            case AnnotationType.FUNCTION_PARAM:
                # Find the function definition and parameter
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                        # Check parameters in this function
                        for arg in node.args.args:
                            # Parameters don't have line numbers in all Python versions,
                            # so we check if the parameter name matches
                            if case.parameter_name and arg.arg == case.parameter_name:
                                # Found the parameter - it has no annotation or inference failed
                                if not arg.annotation:
                                    return "parameter_no_annotation"
                                # Has annotation but inference still failed - likely a bug
                                return "parameter_inference_failed"
                return "parameter_not_found"

            case AnnotationType.FUNCTION_RETURN:
                # Find the function definition and analyze return statements
                for node in ast.walk(tree):
                    if (
                        isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
                        and case.function_name
                        and node.name == case.function_name
                    ):
                        # Found the function - check return statements
                        return_visitor = _ReturnStatementCollector()
                        return_visitor.visit(node)

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


def run_inference_on_case(case: BenchmarkCase) -> InferenceResult:
    """Run inference on single case and categorize result.

    Uses the same TypeAnnotationWorkflow as the LSP server
    to ensure consistent behavior.
    """
    # Get workflow and inference engine from DI container
    container = get_container()
    workflow = container.get(TypeAnnotationWorkflowProtocol)
    inference_engine = container.get(InferenceEngineProtocol)

    # Run inference using the same workflow as LSP server
    inference_result, _, _ = workflow.infer_and_collect_types(case.source_code, str(case.file_path))

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

            try:
                inferred_type = inference_engine.infer_expression_type(
                    case.source_code, case.variable_name
                )
            except Exception as e:
                return InferenceResult(
                    case=case,
                    status=ResultStatus.UNSUPPORTED,
                    inferred_type=None,
                    reason=f"complex_variable_error: {e}",
                )

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


def run_benchmark(
    cases: list[BenchmarkCase],
    show_progress: bool = True,
) -> BenchmarkResults:
    """Run inference on all cases with progress indicator.

    Uses the DI container to get workflow and inference engine instances.
    """
    results = []
    total = len(cases)

    for i, case in enumerate(cases, 1):
        if show_progress and i % 50 == 0:
            print(f"Progress: [{i}/{total}] ({i / total * 100:.1f}%)")

        result = run_inference_on_case(case)
        results.append(result)

    if show_progress:
        print(f"Progress: [{total}/{total}] (100.0%)")

    return BenchmarkResults(total=total, results=results)
