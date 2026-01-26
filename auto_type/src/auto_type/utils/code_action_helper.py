import logging
import re

from injector import inject
from lsprotocol import types
from pygls.lsp.server import LanguageServer

from auto_type.insertion import (
    CodeLocation,
    InsertionTarget,
    TargetType,
    UnifiedInsertionEngine,
)
from auto_type.protocols import (
    InferenceEngineProtocol,
    TypeValidatorProtocol,
)

logger = logging.getLogger(__name__)


class CodeActionHelper:
    """Helper class for providing code actions.

    Methods that use inference or validation are async.
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

    def _find_variable_line(self, source: str, variable_name: str) -> int:
        """Find the line number where a variable is assigned."""
        lines = source.split("\n")
        for i, line in enumerate(lines, 1):
            if f"{variable_name} =" in line and not line.strip().startswith("#"):
                return i
        return 1  # Fallback to line 1

    def _create_variable_target(
        self, name: str, type_annotation: str, line: int
    ) -> InsertionTarget:
        """Create an InsertionTarget for a variable annotation."""
        return InsertionTarget(
            target_type=TargetType.VARIABLE_SIMPLE,
            location=CodeLocation(line=line, column=0),
            type_annotation=type_annotation,
            name=name,
        )

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
        actions = []

        try:
            uri = params.text_document.uri
            doc = ls.workspace.get_text_document(uri)
            source = doc.source

            # Filter diagnostics in the current range with code "type-mismatch"
            for diagnostic in params.context.diagnostics:
                if diagnostic.code != "type-mismatch":
                    continue
                if diagnostic.source != "auto-type":
                    continue

                # Extract information from diagnostic data
                if not diagnostic.data:
                    continue

                inferred_type = diagnostic.data.get("inferred_type")
                var_name = diagnostic.data.get("var_name")

                if not inferred_type or not var_name:
                    continue

                # Use UnifiedInsertionEngine to replace the type
                line = self._find_variable_line(source, var_name)
                target = self._create_variable_target(var_name, inferred_type, line)
                result = self.insertion_engine.insert([target], source)

                if not result.success:
                    logger.warning(
                        f"Failed to create replacement for {var_name}: {result.error_message}"
                    )
                    continue

                modified_source = result.modified_source

                # Create workspace edit
                text_edit = types.TextEdit(
                    range=types.Range(
                        start=types.Position(line=0, character=0),
                        end=types.Position(line=len(source.splitlines()), character=0),
                    ),
                    new_text=modified_source,
                )

                workspace_edit = types.WorkspaceEdit(changes={uri: [text_edit]})

                # Create "Change type to..." action
                action = types.CodeAction(
                    title=f"Change type to '{inferred_type}'",
                    kind=types.CodeActionKind.QuickFix,
                    edit=workspace_edit,
                    diagnostics=[diagnostic],  # Link to diagnostic
                )

                actions.append(action)

                # Also offer "Remove type annotation" as alternative
                remove_action = self.create_remove_type_action(uri, source, var_name, diagnostic)
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

        This method is async because it uses inference and validation engines.

        Args:
            ls: The language server instance
            params: Code action parameters

        Returns:
            List of code actions to insert types
        """
        try:
            uri = params.text_document.uri
            doc = ls.workspace.get_text_document(uri)
            source = doc.source

            # Get the line where the code action was requested
            start_line = params.range.start.line
            line_content = (
                source.splitlines()[start_line] if start_line < len(source.splitlines()) else ""
            )

            # Check if this line has a variable assignment
            # Simple heuristic: look for "var_name = " pattern
            match = re.match(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*", line_content)

            if not match:
                return []

            var_name = match.group(1)

            # Check if variable already has annotation
            if ":" in line_content.split("=")[0]:
                # Already annotated, don't offer action
                return []

            # Get inferred type for this variable (async)
            inference_result = await self.inference_engine.infer_types(source)
            variable_insertions = inference_result.get_variable_insertions()

            # Key is (line, var_name). start_line from LSP is 0-based.
            # get_variable_insertions uses 1-based lines.
            inferred_type = variable_insertions.get((start_line + 1, var_name))

            if not inferred_type:
                return []

            # Validate the type using mypy (async)
            if not await self.type_validator.validate(inferred_type, source):
                return []

            # Insert the type annotation and create a WorkspaceEdit (sync)
            line = self._find_variable_line(source, var_name)
            target = self._create_variable_target(var_name, inferred_type, line)
            result = self.insertion_engine.insert([target], source)

            if not result.success:
                logger.warning(
                    f"Failed to create edit for {var_name}: {inferred_type} - {result.error_message}"
                )
                return []

            modified_source = result.modified_source

            # Create LSP WorkspaceEdit with the modified source
            text_edit = types.TextEdit(
                range=types.Range(
                    start=types.Position(line=0, character=0),
                    end=types.Position(line=len(source.splitlines()), character=0),
                ),
                new_text=modified_source,
            )

            workspace_edit = types.WorkspaceEdit(changes={uri: [text_edit]})

            # Create code action with direct edit (not a command)
            action = types.CodeAction(
                title=f"Insert type annotation: {inferred_type}",
                kind=types.CodeActionKind.QuickFix,
                edit=workspace_edit,  # Direct edit, not a command
            )

            logger.debug(f"Offering code action for {var_name}: {inferred_type}")
            return [action]

        except Exception as e:
            logger.error(f"Error providing insert type actions: {e}", exc_info=True)
            return []
