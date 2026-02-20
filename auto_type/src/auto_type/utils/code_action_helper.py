import logging
import re

from injector import inject
from lsprotocol import types
from pygls.lsp.server import LanguageServer  # noqa: TC002

from auto_type.inference import InferenceResult  # noqa: TC001
from auto_type.insertion import (
    InsertionResult,
    UnifiedInsertionEngine,
    create_variable_target,
    find_variable_line,
)
from auto_type.protocols import (
    InferenceEngineProtocol,  # noqa: TC001
    TypeValidatorProtocol,  # noqa: TC001
)
from auto_type.utils.lsp_request_helper import (
    build_full_document_workspace_edit,
    get_document_context,
)

logger = logging.getLogger(__name__)


class CodeActionHelper:
    """Helper class for providing code actions.

    Methods that perform validation or request handling are async.
    """

    @inject
    def __init__(
        self,
        inference_engine: InferenceEngineProtocol,
        insertion_engine: UnifiedInsertionEngine,
        type_validator: TypeValidatorProtocol,
    ) -> None:
        self.inference_engine = inference_engine
        self.insertion_engine = insertion_engine
        self.type_validator = type_validator

    def get_fix_type_actions(
        self, ls: LanguageServer, params: types.CodeActionParams
    ) -> list[types.CodeAction]:
        """Generate 'Change type to...' actions for type mismatch diagnostics.

        This method is sync because it only uses the insertion engine which
        performs fast CPU-bound operations.

        Args:
            ls: The language server instance
            params: Code action parameters including diagnostics

        Returns:
            List of code actions to fix wrong types
        """
        actions: list[types.CodeAction] = []

        try:
            uri: str = params.text_document.uri
            source: str = get_document_context(ls, uri).source

            # Filter diagnostics in the current range with code "type-mismatch"
            for diagnostic in params.context.diagnostics:
                if diagnostic.code != "type-mismatch":
                    continue
                if diagnostic.source != "auto-type":
                    continue

                # Extract information from diagnostic data
                if not diagnostic.data:
                    continue

                inferred_type: str | None = diagnostic.data.get("inferred_type")
                var_name: str | None = diagnostic.data.get("var_name")

                if not inferred_type or not var_name:
                    continue

                # Use UnifiedInsertionEngine to replace the type
                line: int = find_variable_line(source, var_name)
                target = create_variable_target(var_name, inferred_type, line)
                result: InsertionResult = self.insertion_engine.insert([target], source)

                if not result.success:
                    logger.warning(
                        f"Failed to create replacement for {var_name}: {result.error_message}"
                    )
                    continue

                modified_source: str = result.modified_source

                workspace_edit = build_full_document_workspace_edit(uri, source, modified_source)

                # Create "Change type to..." action
                action: types.CodeAction = types.CodeAction(
                    title=f"Change type to '{inferred_type}'",
                    kind=types.CodeActionKind.QuickFix,
                    edit=workspace_edit,
                    diagnostics=[diagnostic],  # Link to diagnostic
                )

                actions.append(action)

                # Also offer "Remove type annotation" as alternative
                remove_action: types.CodeAction | None = self.create_remove_type_action(
                    uri, source, var_name, diagnostic
                )
                if remove_action:
                    actions.append(remove_action)

        except Exception as e:
            logger.error(f"Error generating fix type actions: {e}", exc_info=True)

        return actions

    def create_remove_type_action(
        self, uri: str, source: str, var_name: str, diagnostic: types.Diagnostic
    ) -> types.CodeAction | None:
        """Create a code action to remove a type annotation.

        This method is sync because it only uses the insertion engine.

        Note: Type removal is not yet implemented in UnifiedInsertionEngine.

        Args:
            uri: Document URI
            source: Document source code
            var_name: Variable name
            diagnostic: The diagnostic this action fixes

        Returns:
            Code action to remove type, or None if creation failed
        """
        try:
            # Type removal not yet implemented in UnifiedInsertionEngine
            logger.info(f"Type removal requested for {var_name} but not yet implemented")
            return None

        except Exception as e:
            logger.error(f"Error creating remove type action: {e}", exc_info=True)
            return None

    async def get_insert_type_actions(
        self, ls: LanguageServer, params: types.CodeActionParams
    ) -> list[types.CodeAction]:
        """Generate 'Insert type annotation' actions for unannotated variables.

        This method is async because it performs request/validation orchestration.

        Args:
            ls: The language server instance
            params: Code action parameters

        Returns:
            List of code actions to insert types
        """
        try:
            uri: str = params.text_document.uri
            doc_context = get_document_context(ls, uri)
            source: str = doc_context.source
            file_path: str = doc_context.file_path

            # Get the line where the code action was requested
            start_line: int = params.range.start.line
            line_content: str = (
                source.splitlines()[start_line] if start_line < len(source.splitlines()) else ""
            )

            # Check if this line has a variable assignment
            # Simple heuristic: look for "var_name = " pattern
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

            # Get inferred type for this variable (sync)
            # IMPORTANT: Pass file_path so Jedi can perform proper inference
            inference_result: InferenceResult = self.inference_engine.infer_types(
                source, path=file_path
            )
            variable_insertions: dict[tuple[int, str], str] = (
                inference_result.get_variable_insertions()
            )

            # Key is (line, var_name). Both start_line from LSP and
            # get_variable_insertions use 0-based lines.
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

            # Insert the type annotation and create a WorkspaceEdit (sync)
            line: int = find_variable_line(source, var_name)
            target = create_variable_target(var_name, inferred_type, line)
            result: InsertionResult = self.insertion_engine.insert([target], source)

            if not result.success:
                logger.warning(
                    f"Failed to create edit for {var_name}: {inferred_type} - "
                    f"{result.error_message}"
                )
                return []

            modified_source: str = result.modified_source

            workspace_edit = build_full_document_workspace_edit(uri, source, modified_source)

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
