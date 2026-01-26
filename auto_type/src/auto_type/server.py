"""Auto-type Language Server - Interactive Python type annotation tool."""

import logging
from typing import Any

from lsprotocol import types
from pygls.lsp.server import LanguageServer

from auto_type import __version__
from auto_type.container import get_container
from auto_type.protocols import (
    TypeAnnotationWorkflowProtocol,
)
from auto_type.utils.code_action_helper import CodeActionHelper
from auto_type.utils.diagnostic_helper import DiagnosticHelper
from auto_type.utils.inlay_hint_helper import InlayHintHelper
from auto_type.utils.uri_helper import UriHelper

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize server
server = LanguageServer("auto-type", f"v{__version__}")


@server.feature(types.TEXT_DOCUMENT_INLAY_HINT)
async def inlay_hints(params: types.InlayHintParams) -> list[types.InlayHint]:
    """Provide type inlay hints for Python variables.

    This handler is called by the editor when it needs to display ghost text
    showing inferred types. It delegates to the TypeAnnotationWorkflow for
    inference and validation, then uses InlayHintHelper for hint generation.

    Args:
        params: Parameters including document URI and visible range

    Returns:
        List of inlay hints to display
    """
    logger.info(f"Inlay hints requested for {params.text_document.uri}")
    logger.info(f"Requested range: lines {params.range.start.line} to {params.range.end.line}")

    try:
        # Get document from workspace
        doc = server.workspace.get_text_document(params.text_document.uri)
        source = doc.source
        file_path = UriHelper.uri_to_path(params.text_document.uri)

        # Get workflow and helpers from container
        container = get_container()
        workflow = container.get(TypeAnnotationWorkflowProtocol)
        inlay_hint_helper = container.get(InlayHintHelper)

        # PHASE 1-2: Collect and validate types (delegated to workflow) - async
        logger.info(f"Starting type inference and validation for {file_path}")

        inference_result, validated_types = await workflow.collect_and_validate_types(
            source, file_path
        )

        logger.info(f"Phase 1-2 (Collection + Validation): {len(validated_types)} types completed")

        # PHASE 3: Generate declaration hints using pre-validated types
        hints: list[types.InlayHint] = []

        for scope_id, scope_obj in inference_result.scope_tree.scopes_by_id.items():
            hints.extend(
                inlay_hint_helper.generate_hints_for_scope(
                    scope_obj, source, validated_types, scope_id
                )
            )

        logger.info(f"Phase 3 (Declaration Hints): {len(hints)} hints generated")

        # PHASE 4: Generate usage-site hints
        usage_hints = await inlay_hint_helper.process_usage_hints(
            source=source,
            file_path=file_path,
            range_start_line=params.range.start.line,
            range_end_line=params.range.end.line,
            inference_result=inference_result,
        )
        hints.extend(usage_hints)

        # Filter hints to requested range
        filtered_hints = [
            hint
            for hint in hints
            if params.range.start.line <= hint.position.line <= params.range.end.line
        ]

        logger.info(
            f"Generated {len(hints)} total hints, returning {len(filtered_hints)} hints "
            f"in range [{params.range.start.line}, {params.range.end.line}]"
        )
        return filtered_hints

    except Exception as e:
        logger.error(f"Error providing inlay hints: {e}", exc_info=True)
        return []


@server.feature(types.TEXT_DOCUMENT_DID_OPEN)
async def did_open(params: types.DidOpenTextDocumentParams) -> None:
    """Handle document open event and run diagnostics."""
    uri = params.text_document.uri
    logger.info(f"Document opened: {uri}")

    # Run diagnostics on file open (async)
    doc = server.workspace.get_text_document(uri)
    injector = get_container()
    diagnostic_helper = injector.get(DiagnosticHelper)
    await diagnostic_helper.run_diagnostics(server, uri, doc.source)


@server.feature(types.TEXT_DOCUMENT_DID_CHANGE)
async def did_change(params: types.DidChangeTextDocumentParams) -> None:
    """Handle document change event with debounced diagnostics."""
    uri = params.text_document.uri
    logger.debug(f"Document changed: {uri}")

    # Schedule diagnostics using helper
    injector = get_container()
    diagnostic_helper = injector.get(DiagnosticHelper)
    diagnostic_helper.schedule_diagnostics(server, uri)


@server.feature(types.TEXT_DOCUMENT_DID_SAVE)
async def did_save(params: types.DidSaveTextDocumentParams) -> None:
    """Handle document save event and run diagnostics."""
    uri = params.text_document.uri
    logger.info(f"Document saved: {uri}")

    # Run diagnostics on save (async)
    doc = server.workspace.get_text_document(uri)
    injector = get_container()
    diagnostic_helper = injector.get(DiagnosticHelper)
    await diagnostic_helper.run_diagnostics(server, uri, doc.source)


# Custom LSP requests for type insertion


@server.feature("auto_type/insertType")
async def insert_type(ls: LanguageServer, params: list[Any]) -> dict[str, Any]:
    """Insert a type annotation for a single variable.

    Custom LSP request that inserts a type annotation at a specific position.
    Called from VSCode when user triggers "Insert type annotation" command.

    Args:
        ls: The language server instance
        params: List with [uri, variable_name, type_annotation, line_number?]
            line_number is optional (0-based)

    Returns:
        Dict with:
        - "success": bool
        - "edits": WorkspaceEdit to apply (if success)
        - "message": str (error message if not success)
    """
    try:
        uri = params[0]
        variable_name = params[1]
        type_annotation = params[2]
        line_number = params[3] if len(params) > 3 else None

        logger.info(
            f"Insert type request: {variable_name}: {type_annotation} "
            f"at line {line_number if line_number is not None else 'any'} in {uri}"
        )

        # Get document
        doc = ls.workspace.get_text_document(uri)
        source = doc.source

        # Use workflow for insertion (async)
        workflow = get_container().get(TypeAnnotationWorkflowProtocol)

        # Pass 1-based line number to insertion engine if provided
        # LSP uses 0-based, InsertionEngine uses 1-based
        target_line = (line_number + 1) if line_number is not None else None

        modified_source, success, message = await workflow.insert_single_type(
            source, variable_name, type_annotation, line_number=target_line
        )

        if not success:
            logger.warning(message)
            return {"success": False, "message": message}

        # Create LSP WorkspaceEdit
        text_edit = types.TextEdit(
            range=types.Range(
                start=types.Position(line=0, character=0),
                end=types.Position(line=len(source.splitlines()), character=0),
            ),
            new_text=modified_source,
        )

        workspace_edit = types.WorkspaceEdit(changes={uri: [text_edit]})

        logger.info(f"Successfully created edit for {variable_name}")
        return {"success": True, "edits": workspace_edit}

    except Exception as e:
        logger.error(f"Error in insert_type: {e}", exc_info=True)
        return {"success": False, "message": f"Internal error: {e!s}"}


@server.feature("auto_type/insertTypesInFile")
async def insert_types_in_file(ls: LanguageServer, params: Any) -> dict[str, Any]:
    """Insert type annotations for all inferred types in a file.

    Custom LSP request that inserts all inferred type annotations at once,
    including module-level variables AND function signatures (parameters + return types).
    Called from VSCode when user triggers "Insert all types" command.

    Args:
        ls: The language server instance
        params: List with [uri]

    Returns:
        Dict with:
        - "success": bool
        - "edits": WorkspaceEdit to apply (if success)
        - "inserted_count": int (variables + functions)
        - "skipped_count": int
        - "message": str
    """
    try:
        # Extract URI from parameters
        uri = UriHelper.extract_uri(params)
        logger.info(f"Insert all types request for {uri}")

        # Get document
        doc = ls.workspace.get_text_document(uri)
        source = doc.source
        file_path = UriHelper.uri_to_path(uri)

        # Use workflow for insertion (async)
        workflow = get_container().get(TypeAnnotationWorkflowProtocol)
        modified_source, var_count, func_count, message = await workflow.insert_all_types(
            source, file_path, skip_annotated=True
        )

        total_inserted = var_count + func_count
        if total_inserted == 0:
            logger.info(message)
            return {
                "success": False,
                "message": message,
                "inserted_count": 0,
                "skipped_count": 0,
            }

        # Create LSP WorkspaceEdit
        text_edit = types.TextEdit(
            range=types.Range(
                start=types.Position(line=0, character=0),
                end=types.Position(line=len(source.splitlines()), character=0),
            ),
            new_text=modified_source,
        )

        workspace_edit = types.WorkspaceEdit(changes={uri: [text_edit]})

        logger.info(message)
        return {
            "success": True,
            "edits": workspace_edit,
            "inserted_count": total_inserted,
            "skipped_count": 0,
            "message": message,
        }

    except Exception as e:
        logger.error(f"Error in insert_types_in_file: {e}", exc_info=True)
        return {
            "success": False,
            "message": f"Internal error: {e!s}",
            "inserted_count": 0,
            "skipped_count": 0,
        }


@server.feature("auto_type/previewInserts")
async def preview_inserts(ls: LanguageServer, params: Any) -> dict[str, Any]:
    """Preview what type annotations would be inserted without modifying code.

    Custom LSP request that shows a preview of what insertions would be made.
    Used for the bulk insertion preview dialog.

    Args:
        ls: The language server instance
        params: List with [uri]

    Returns:
        Dict with:
        - "success": bool
        - "will_insert": list[dict] with changes to be made
        - "will_skip": list[dict] with skipped variables
        - "total_changes": int
    """
    try:
        # Extract URI from parameters
        uri = UriHelper.extract_uri(params)
        logger.info(f"Preview inserts request for {uri}")

        # Get document
        doc = ls.workspace.get_text_document(uri)
        source = doc.source

        # Use workflow for preview (async)
        workflow = get_container().get(TypeAnnotationWorkflowProtocol)
        preview = await workflow.preview_insertions(source)
        total = preview["total_changes"]
        skipped = len(preview.get("will_skip", []))
        logger.info(f"Preview: {total} insertions, {skipped} skipped")

        return preview

    except Exception as e:
        logger.error(f"Error in preview_inserts: {e}", exc_info=True)
        return {
            "success": False,
            "will_insert": [],
            "will_skip": [],
            "total_changes": 0,
            "message": f"Internal error: {e!s}",
        }


@server.feature("auto_type/removeTypesInFile")
async def remove_types_in_file(ls: LanguageServer, params: Any) -> dict[str, Any]:
    """Remove type annotations from variables in a file.

    Custom LSP request that removes type annotations from specified variables
    or all variables in a file. Called from VSCode when user triggers
    "Remove type annotations" command.

    Args:
        ls: The language server instance
        params: List with [uri, variables, include_functions]
            - uri: str (document URI)
            - variables: list[str] | None (None = remove all)
            - include_functions: bool (default False, not yet implemented)

    Returns:
        Dict with:
        - "success": bool
        - "edits": WorkspaceEdit to apply (if success)
        - "removed_count": int
        - "not_found": list[str]
        - "skipped": list[str]
        - "message": str
    """
    try:
        # Extract URI and optional parameters
        uri, optional_params = UriHelper.extract_uri_with_optional_params(params, num_optional=2)
        variables = optional_params[0] if optional_params[0] is not None else None
        include_functions = bool(optional_params[1]) if optional_params[1] is not None else False

        logger.info(
            f"Remove types request for {uri} "
            f"(variables={variables}, include_functions={include_functions})"
        )

        # Get document
        doc = ls.workspace.get_text_document(uri)
        source = doc.source

        # Use workflow for removal (sync - fast CPU-bound operation)
        workflow = get_container().get(TypeAnnotationWorkflowProtocol)
        modified_source, result_info = workflow.remove_types(source, variables, include_functions)

        if not result_info["success"]:
            return {
                "success": False,
                "message": "No type annotations found to remove",
                "removed_count": 0,
                "not_found": result_info.get("not_found", []),
                "skipped": result_info.get("skipped", []),
            }

        # Create LSP WorkspaceEdit
        text_edit = types.TextEdit(
            range=types.Range(
                start=types.Position(line=0, character=0),
                end=types.Position(line=len(source.splitlines()), character=0),
            ),
            new_text=modified_source,
        )

        workspace_edit = types.WorkspaceEdit(changes={uri: [text_edit]})

        removed_count = result_info["removed_count"]
        not_found = result_info.get("not_found", [])
        skipped = result_info.get("skipped", [])

        # Build message
        if variables is None:
            message = f"Removed {removed_count} type annotation(s) from file."
        else:
            message = f"Removed {removed_count} type annotation(s)."

        if skipped:
            message += f" Skipped {len(skipped)} variable(s) without values."
        if not_found:
            message += f" {len(not_found)} variable(s) not found or not annotated."

        logger.info(message)
        return {
            "success": True,
            "edits": workspace_edit,
            "removed_count": removed_count,
            "not_found": not_found,
            "skipped": skipped,
            "message": message,
        }

    except Exception as e:
        logger.error(f"Error in remove_types_in_file: {e}", exc_info=True)
        return {
            "success": False,
            "message": f"Internal error: {e!s}",
            "removed_count": 0,
            "not_found": [],
            "skipped": [],
        }


@server.feature("auto_type/previewRemovals")
def preview_removals(ls: LanguageServer, params: Any) -> dict[str, Any]:
    """Preview what type annotations would be removed without modifying code.

    Custom LSP request that shows a preview of what removals would be made.
    Used for the bulk removal preview dialog.

    This handler is sync because it only uses the insertion engine which
    performs fast CPU-bound operations.

    Args:
        ls: The language server instance
        params: List with [uri, variables]
            - uri: str (document URI)
            - variables: list[str] | None (None = preview all)

    Returns:
        Dict with:
        - "success": bool
        - "will_remove": list[dict] with variables that will be removed
        - "not_found": list[str] with variables not found
        - "will_skip": list[dict] with variables that will be skipped
        - "total_changes": int
    """
    try:
        # Extract URI and optional parameters
        uri, optional_params = UriHelper.extract_uri_with_optional_params(params, num_optional=1)
        variables = optional_params[0] if optional_params[0] is not None else None

        logger.info(f"Preview removals request for {uri} (variables={variables})")

        # Get document
        doc = ls.workspace.get_text_document(uri)
        source = doc.source

        workflow = get_container().get(TypeAnnotationWorkflowProtocol)

        # Get preview (sync - fast CPU-bound operation)
        preview = workflow.preview_removals(source, variables)

        logger.info(
            f"Preview: {preview['total_changes']} removals, "
            f"{len(preview.get('will_skip', []))} skipped, "
            f"{len(preview.get('not_found', []))} not found"
        )

        return preview

    except Exception as e:
        logger.error(f"Error in preview_removals: {e}", exc_info=True)
        return {
            "success": False,
            "will_remove": [],
            "not_found": [],
            "will_skip": [],
            "total_changes": 0,
            "message": f"Internal error: {e!s}",
        }


@server.feature(types.TEXT_DOCUMENT_CODE_ACTION)
async def code_actions(params: types.CodeActionParams) -> list[types.CodeAction]:
    """Provide code actions (lightbulb menu) for inserting and fixing type annotations.

    This handler is called when the user opens the lightbulb menu or hovers
    over ghost text. It provides quick fix actions to:
    1. Insert type annotations for unannotated variables
    2. Fix type annotations that don't match the inferred type

    Args:
        params: Code action parameters including document URI and range

    Returns:
        List of code actions available at the given position
    """
    actions = []

    injector = get_container()
    code_action_helper = injector.get(CodeActionHelper)

    # Add "Fix wrong type" actions for diagnostics (sync)
    actions.extend(code_action_helper.get_fix_type_actions(server, params))

    # Add "Insert type" actions for unannotated variables (async)
    actions.extend(await code_action_helper.get_insert_type_actions(server, params))

    return actions


def main() -> None:
    """Start the auto-type language server."""
    logger.info("Starting auto-type language server...")
    server.start_io()


if __name__ == "__main__":
    main()
