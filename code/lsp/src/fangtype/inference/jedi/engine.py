"""Jedi-based synchronous type inference engine (infer/execute, Script.infer/get_names)."""

import ast
import logging
from typing import Any

import jedi
from injector import inject

from fangtype.analysis import Scope, ScopeTree, ScopeType
from fangtype.cancellation import CancellationToken
from fangtype.inference.inference_result import InferenceResult
from fangtype.inference.jedi.project import find_project_root
from fangtype.inference.jedi.scope_builder import build_scope_tree
from fangtype.inference.jedi.type_formatter import format_types
from fangtype.utils.settings import Settings

logger = logging.getLogger(__name__)


class JediInferenceEngine:
    """Jedi-based type inference engine."""

    @inject
    def __init__(self, settings: Settings) -> None:
        """Init; settings is the DI singleton read per call for cross_file_contracts_enabled."""
        self._settings = settings
        self._env: Any | None = None

    def _get_env(self) -> Any:
        """Get or create the Jedi environment (cached)."""
        if self._env is None:
            self._env = self._build_env()
        return self._env

    def _build_env(self) -> Any:
        """Jedi env: project_interpreter (managed venv) else SameEnvironment; default on failure."""
        interpreter = self._settings.project_interpreter
        if interpreter:
            try:
                return jedi.api.environment.create_environment(interpreter, safe=False)
            except Exception as e:
                logger.warning(
                    f"Failed to create Jedi environment for {interpreter!r}, falling back: {e}"
                )
        try:
            # SameEnvironment uses the current process environment.
            return jedi.api.environment.SameEnvironment()
        except Exception as e:
            logger.warning(f"Failed to create SameEnvironment, falling back to default: {e}")
            return jedi.get_default_environment()

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
        # is_complete=False: a degraded fallback the DocumentCache must never store.
        return InferenceResult(scope_tree=scope_tree, source=source, is_complete=False)

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

    def _cancel_token(self, cancel_token: CancellationToken | None) -> CancellationToken:
        """Resolve the effective cancel token, defaulting to a never-cancelled one."""
        return cancel_token or CancellationToken()

    def infer_types(
        self,
        source: str,
        path: str | None = None,
        project_root: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> InferenceResult:
        """Pure-compute full inference (caching lives in DocumentCache); cancel yields partial."""
        cancel_token = self._cancel_token(cancel_token)
        enable_cross_file = self._settings.cross_file_contracts_enabled

        # A file that does not parse has no types to infer, and the empty result is the
        # right answer rather than a failure. Kept separate from the Jedi call below so
        # the two are not conflated.
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            logger.debug("Source does not parse, no types to infer: %s", e)
            return self._create_empty_result(source)

        try:
            return self._build_scope_tree_result(
                source, tree, path, project_root, enable_cross_file, cancel_token
            )
        except Exception as first:
            # Jedi reads parso's module-global parse cache unguarded, so an evicted entry
            # surfaces here as a KeyError from deep inside name resolution. Rebuilding the
            # Script re-parses and repopulates that cache for the paths it touches, so one
            # retry is self-healing rather than hopeful. Same shape as the retry-once in
            # validation/mypy_runner.py.
            logger.warning("Jedi inference failed for %s (%s); retrying once", path, first)
            try:
                return self._build_scope_tree_result(
                    source, tree, path, project_root, enable_cross_file, cancel_token
                )
            except Exception as second:
                logger.error("Jedi inference failed again for %s: %s", path, second, exc_info=True)
                return self._create_empty_result(source)

    def _build_scope_tree_result(
        self,
        source: str,
        tree: ast.Module,
        path: str | None,
        project_root: str | None,
        enable_cross_file: bool,
        cancel_token: CancellationToken,
    ) -> InferenceResult:
        """Build the Script and scope tree, and wrap them as an ``InferenceResult``.

        A degraded tree is marked incomplete so ``DocumentCache`` refuses it; see
        ``build_scope_tree`` for when that happens.
        """
        script = self._build_script(source, path, project_root)
        scope_tree = build_scope_tree(
            script, tree, enable_cross_file=enable_cross_file, cancel_token=cancel_token
        )
        return InferenceResult(
            scope_tree=scope_tree, source=source, is_complete=not scope_tree.degraded
        )

    def infer_types_at_locations(
        self,
        source: str,
        locations: list[tuple[int, int]],
        path: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> dict[tuple[int, int], str]:
        """Infer types at multiple specific locations in the source code."""
        cancel_token = self._cancel_token(cancel_token)
        if not locations:
            return {}

        try:
            results: dict[tuple[int, int], str] = {}
            script = self._build_script(source, path, None)

            for line, col in locations:
                if cancel_token.cancelled():
                    break
                try:
                    inferences = script.infer(line, col)
                except ValueError:
                    logger.debug(
                        "Skipping invalid location for inference: line=%s col=%s", line, col
                    )
                    continue
                except Exception as e:
                    # Jedi/parso may raise deep internally; drop only this location, keep the rest.
                    logger.warning("Jedi inference failed at line=%s col=%s: %s", line, col, e)
                    continue
                if inferences:
                    type_str = format_types(list(inferences))
                    if type_str and type_str != "Unknown":
                        results[(line, col)] = type_str

            return results
        except Exception as e:
            logger.error(f"Error in infer_types_at_locations: {e}", exc_info=True)
            return {}
