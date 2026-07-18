import asyncio
import logging
import re
from typing import TYPE_CHECKING

from injector import inject
from lsprotocol import types
from pygls.lsp.server import LanguageServer

from fangtype.insertion import (
    InsertionEngine,
    InsertionResult,
    TargetType,
    create_variable_target,
    find_assignment_target,
    find_variable_line,
)
from fangtype.protocols import (
    InferenceEngineProtocol,
    TypeValidatorProtocol,
)
from fangtype.utils.document_cache import DocumentCache
from fangtype.utils.lsp_request_helper import (
    build_full_document_workspace_edit,
    get_document_context,
)
from fangtype.utils.position_encoding import ast_source_lines
from fangtype.utils.settings import Settings

if TYPE_CHECKING:
    from fangtype.inference import InferenceResult

logger = logging.getLogger(__name__)


class CodeActionHelper:
    """Helper for code actions; validation/request-handling methods are async."""

    # @inject leaks Any via its overloads; no call-site annotation satisfies disallow_any_expr.
    @inject  # type: ignore[misc]
    def __init__(
        self,
        inference_engine: InferenceEngineProtocol,
        insertion_engine: InsertionEngine,
        type_validator: TypeValidatorProtocol,
        document_cache: DocumentCache,
        settings: Settings,
    ) -> None:
        self.inference_engine = inference_engine
        self.insertion_engine = insertion_engine
        self.type_validator = type_validator
        self.document_cache = document_cache
        self.settings = settings

    async def get_insert_type_actions(
        self, ls: LanguageServer, params: types.CodeActionParams
    ) -> list[types.CodeAction]:
        """Generate 'Insert type annotation' actions for unannotated variables (async)."""
        try:
            uri: str = params.text_document.uri
            doc_context = get_document_context(ls, uri)
            source: str = doc_context.source
            file_path: str = doc_context.file_path

            # Get the line where the code action was requested
            start_line: int = params.range.start.line
            # LSP lines break only on \n/\r/\r\n; ast_source_lines matches (unlike str.splitlines).
            source_lines = ast_source_lines(source)
            line_content: str = source_lines[start_line] if start_line < len(source_lines) else ""

            # Heuristic: only offer the action on a "var_name = " assignment line.
            match: re.Match[str] | None = re.match(
                r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*", line_content
            )

            if not match:
                return []

            var_name: str = match.group(1)

            # Check if variable already has annotation
            if ":" in line_content.split("=")[0]:
                # Already annotated, don't offer action
                return []

            # Reuse the DocumentCache when unchanged; file_path is required for real Jedi inference.
            generation = self.settings.generation
            version = doc_context.version
            inference_result: InferenceResult | None = self.document_cache.get(
                uri, version, generation, source
            )
            if inference_result is None:
                inference_result = await asyncio.to_thread(
                    self.inference_engine.infer_types,
                    source,
                    path=file_path,
                    project_root=self.settings.project_root,
                )
                if inference_result.is_complete:
                    self.document_cache.put(uri, version, generation, source, inference_result)
            variable_insertions: dict[tuple[int, str], str] = (
                inference_result.get_variable_insertions()
            )

            # Key (line, var_name); both start_line and get_variable_insertions use 0-based lines.
            inferred_type: str | None = variable_insertions.get((start_line, var_name))

            if not inferred_type:
                return []

            # Validate the type using mypy (async)
            validation_result = await self.type_validator.validate_bulk(
                {"_single": inferred_type},
                source,
            )
            single_result = validation_result.get("_single")
            if not single_result or not single_result.is_valid:
                return []

            # Insert annotation; resolve via clicked-line so a repeated name hits the clicked one.
            resolved = find_assignment_target(source, var_name, start_line)
            if resolved is not None:
                line = resolved.line_1_based
                target_type = resolved.target_type
            else:
                line = find_variable_line(source, var_name)
                target_type = TargetType.VARIABLE_SIMPLE
            target = create_variable_target(var_name, inferred_type, line, target_type=target_type)
            result: InsertionResult = self.insertion_engine.insert([target], source)

            if not result.success:
                logger.warning(
                    f"Failed to create edit for {var_name}: {inferred_type} - "
                    f"{result.error_message}"
                )
                return []

            modified_source: str = result.modified_source

            workspace_edit = build_full_document_workspace_edit(
                uri, source, modified_source, doc_context.version
            )

            # Create code action with direct edit (not a command)
            action: types.CodeAction = types.CodeAction(
                title=f"Insert type annotation: {inferred_type}",
                kind=types.CodeActionKind.QuickFix,
                edit=workspace_edit,  # Direct edit, not a command
            )

            logger.debug(f"Offering code action for {var_name}: {inferred_type}")
            return [action]

        except Exception as e:
            logger.error(f"Error providing insert type actions: {e}", exc_info=True)
            return []
