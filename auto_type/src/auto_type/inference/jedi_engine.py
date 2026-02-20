"""Jedi-based type inference engine for Python.

Key Jedi APIs used:
- Name.get_type_hint() - Extract explicit type annotations
- Name.execute() - Analyze function return values
- Name.infer() - General type inference
- Script.infer(line, col) - Positional type inference
- Script.get_names() - Get all definitions in code

All public methods are synchronous and execute inline.
"""

import ast
import logging
from typing import Any

import jedi

from auto_type.analysis import Scope, ScopeTree, ScopeType
from auto_type.inference.inference_result import InferenceResult
from auto_type.inference.jedi_project import find_project_root
from auto_type.inference.jedi_scope_builder import build_scope_tree
from auto_type.inference.jedi_type_formatter import format_types

logger = logging.getLogger(__name__)


class JediInferenceEngine:
    """Jedi-based type inference engine."""

    def __init__(self) -> None:
        """Initialize the Jedi inference engine."""
        self._env: Any | None = None

    def _get_env(self) -> Any:
        """Get or create the Jedi environment (cached)."""
        if self._env is None:
            try:
                # SameEnvironment uses the current process environment.
                self._env = jedi.api.environment.SameEnvironment()
            except Exception as e:
                logger.warning(f"Failed to create SameEnvironment, falling back to default: {e}")
                self._env = jedi.get_default_environment()
        return self._env

    def _create_empty_result(self, source: str) -> InferenceResult:
        """Create a safe fallback inference result with only module scope."""
        module_scope = Scope(
            scope_id="module",
            scope_type=ScopeType.MODULE,
            name="<module>",
            ast_node=ast.Module(body=[], type_ignores=[]),
        )
        scope_tree = ScopeTree(root=module_scope)
        scope_tree.add_scope(module_scope)
        return InferenceResult(scope_tree=scope_tree, source=source)

    def _build_script(
        self,
        source: str,
        path: str | None = None,
        project_root: str | None = None,
    ) -> jedi.Script:
        """Build a Jedi Script with project-aware settings."""
        validated_path, project = find_project_root(path, project_root)
        env = self._get_env()

        logger.info(
            f"Jedi inference: path={path}, validated_path={validated_path}, "
            f"has_project={project is not None}"
        )

        return jedi.Script(source, path=validated_path, project=project, environment=env)

    def infer_types(
        self,
        source: str,
        path: str | None = None,
        project_root: str | None = None,
    ) -> InferenceResult:
        """Perform complete type inference on Python source code using Jedi."""
        try:
            tree = ast.parse(source)
            script = self._build_script(source, path, project_root)
            scope_tree = build_scope_tree(script, tree)
            return InferenceResult(scope_tree=scope_tree, source=source)
        except Exception as e:
            logger.error(f"Error in Jedi inference: {e}", exc_info=True)
            return self._create_empty_result(source)

    def infer_types_at_locations(
        self,
        source: str,
        locations: list[tuple[int, int]],
        path: str | None = None,
    ) -> dict[tuple[int, int], str]:
        """Infer types at multiple specific locations in the source code."""
        if not locations:
            return {}

        try:
            results: dict[tuple[int, int], str] = {}
            script = self._build_script(source, path, None)

            for line, col in locations:
                try:
                    inferences = script.infer(line, col)
                except ValueError:
                    logger.debug(
                        "Skipping invalid location for inference: line=%s col=%s", line, col
                    )
                    continue
                if inferences:
                    type_str = format_types(list(inferences))
                    if type_str and type_str != "Unknown":
                        results[(line, col)] = type_str

            return results
        except Exception as e:
            logger.error(f"Error in infer_types_at_locations: {e}", exc_info=True)
            return {}

    def infer_expression_type(
        self,
        source: str,
        expression: str,
        path: str | None = None,
        line_hint: int | None = None,
    ) -> str | None:
        """Infer type of any Python expression using synthetic assignment query."""
        if not expression.strip():
            return None

        synthetic_code = source.rstrip() + "\n" + f"__jedi_query_temp__ = {expression}\n"
        synthetic_line = None
        for i, line in enumerate(synthetic_code.splitlines(), 1):
            if "__jedi_query_temp__" in line:
                synthetic_line = i
                break

        if synthetic_line is None:
            return None

        try:
            script = self._build_script(synthetic_code, path, None)
            query_line = synthetic_code.splitlines()[synthetic_line - 1]
            probe_cols = [
                0,
                max(len(query_line) - 1, 0),
                query_line.find("__jedi_query_temp__"),
                query_line.find("=") + 2 if "=" in query_line else -1,
            ]

            if line_hint is not None and 1 <= line_hint <= len(synthetic_code.splitlines()):
                # Probe around the original line for better local context when available.
                original_line = synthetic_code.splitlines()[line_hint - 1]
                probe_cols.extend([0, max(len(original_line) - 1, 0)])
                for token in (".", "[", "]"):
                    idx = original_line.find(token)
                    if idx != -1:
                        probe_cols.append(idx)

            for col in probe_cols:
                if col < 0:
                    continue
                try:
                    inferences = script.infer(synthetic_line, col)
                except ValueError:
                    continue
                type_str = format_types(list(inferences))
                if type_str and type_str != "Unknown":
                    return type_str

            return None
        except Exception as e:
            logger.debug(f"Failed to infer expression type for '{expression}': {e}")
            return None
