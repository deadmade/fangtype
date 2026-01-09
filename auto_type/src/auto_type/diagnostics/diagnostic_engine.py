"""Engine for generating diagnostics for type mismatches."""

import ast
from dataclasses import dataclass

from lsprotocol import types

from auto_type.inference.literal_inference import LiteralInferenceEngine


@dataclass
class AnnotatedAssignment:
    """Represents an annotated variable assignment."""

    var_name: str
    annotation: str
    value_node: ast.expr  # The AST node for the value
    line: int
    col_start: int
    col_end: int


class DiagnosticEngine:
    """Detects type mismatches between annotations and inferred types."""

    def __init__(self, inference_engine: LiteralInferenceEngine) -> None:
        """Initialize the diagnostic engine.

        Args:
            inference_engine: The literal inference engine to use for type inference
        """
        self.inference_engine = inference_engine

    def generate_diagnostics(self, source: str, uri: str) -> list[types.Diagnostic]:
        """Find all type mismatches in the source code.

        Args:
            source: The Python source code to analyze
            uri: The document URI (for logging/debugging)

        Returns:
            List of LSP Diagnostic objects for each mismatch
        """
        diagnostics: list[types.Diagnostic] = []

        # Find all annotated assignments in the source
        annotated_assignments = self._find_annotated_assignments(source)

        # Check each annotated assignment for mismatches
        for assignment in annotated_assignments:
            # Infer the type from the value node directly
            inferred_type = self.inference_engine.infer_from_node(assignment.value_node)

            # Skip if we couldn't infer a type for this variable
            if inferred_type is None:
                continue

            # Check for mismatch
            if self._detect_mismatch(assignment.annotation, inferred_type):
                diagnostic = self._create_diagnostic(
                    assignment.var_name,
                    assignment.annotation,
                    inferred_type,
                    assignment.line,
                    assignment.col_start,
                    assignment.col_end,
                )
                diagnostics.append(diagnostic)

        return diagnostics

    def _find_annotated_assignments(self, source: str) -> list[AnnotatedAssignment]:
        """Parse AST to find all annotated assignments.

        Example: x: str = 42

        Args:
            source: The Python source code to parse

        Returns:
            List of AnnotatedAssignment objects
        """
        assignments: list[AnnotatedAssignment] = []

        try:
            tree = ast.parse(source)
        except SyntaxError:
            # If source has syntax errors, return empty list
            return []

        for node in ast.walk(tree):
            if isinstance(node, ast.AnnAssign):
                # Only handle simple name targets (not attributes or subscripts)
                if isinstance(node.target, ast.Name) and node.value is not None:
                    var_name = node.target.id

                    # Get the annotation as a string
                    try:
                        annotation = ast.unparse(node.annotation)
                    except Exception:
                        # Skip if we can't unparse the annotation
                        continue

                    # Get position information
                    # The range should cover the annotation part only
                    if hasattr(node.annotation, "lineno") and hasattr(
                        node.annotation, "col_offset"
                    ):
                        line = node.annotation.lineno - 1  # Convert to 0-based
                        col_start = node.annotation.col_offset

                        # Calculate end column (ensure it's always an int)
                        if hasattr(node.annotation, "end_col_offset") and node.annotation.end_col_offset is not None:
                            col_end = node.annotation.end_col_offset
                        else:
                            # Fallback: estimate based on annotation length
                            col_end = col_start + len(annotation)

                        assignments.append(
                            AnnotatedAssignment(
                                var_name=var_name,
                                annotation=annotation,
                                value_node=node.value,  # Include the value AST node
                                line=line,
                                col_start=col_start,
                                col_end=col_end,
                            )
                        )

        return assignments

    def _detect_mismatch(self, annotation: str, inferred_type: str) -> bool:
        """Compare annotation with inferred type.

        Args:
            annotation: The type annotation string (e.g., "str")
            inferred_type: The inferred type string (e.g., "int")

        Returns:
            True if there's a mismatch, False if they match
        """
        # Normalize both types for comparison
        normalized_annotation = self._normalize_type(annotation)
        normalized_inferred = self._normalize_type(inferred_type)

        return normalized_annotation != normalized_inferred

    def _normalize_type(self, type_str: str) -> str:
        """Normalize a type string for comparison.

        Handles equivalences like:
        - List[int] vs list[int]
        - Optional[str] vs str | None

        Args:
            type_str: The type string to normalize

        Returns:
            Normalized type string
        """
        # Strip whitespace
        normalized = type_str.strip()

        # Convert typing module types to built-in equivalents
        # List -> list, Dict -> dict, Set -> set, Tuple -> tuple
        replacements = {
            "List": "list",
            "Dict": "dict",
            "Set": "set",
            "Tuple": "tuple",
        }

        for old, new in replacements.items():
            if normalized.startswith(old + "["):
                normalized = new + normalized[len(old) :]

        return normalized

    def _create_diagnostic(
        self,
        var_name: str,
        annotation: str,
        inferred_type: str,
        line: int,
        col_start: int,
        col_end: int,
    ) -> types.Diagnostic:
        """Create an LSP Diagnostic object for the mismatch.

        Args:
            var_name: The variable name
            annotation: The existing annotation
            inferred_type: The inferred type
            line: Line number (0-based)
            col_start: Start column (0-based)
            col_end: End column (0-based)

        Returns:
            LSP Diagnostic object
        """
        return types.Diagnostic(
            range=types.Range(
                start=types.Position(line=line, character=col_start),
                end=types.Position(line=line, character=col_end),
            ),
            severity=types.DiagnosticSeverity.Warning,
            source="auto-type",
            message=f"Type '{annotation}' doesn't match inferred type '{inferred_type}'",
            code="type-mismatch",
            data={
                "inferred_type": inferred_type,
                "var_name": var_name,
                "annotation": annotation,
            },
        )
