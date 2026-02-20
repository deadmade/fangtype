"""Auto-type Language Server - Interactive Python type annotation tool."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
import time
from typing import TYPE_CHECKING, Any, cast

asyncio.iscoroutinefunction = inspect.iscoroutinefunction

from pygls.lsp.server import LanguageServer

from auto_type import __version__
from auto_type.container import get_container
from auto_type.utils import (
    CodeActionHelper,
    InlayHintHelper,
    Settings,
    build_full_document_workspace_edit,
    extract_uri_and_context,
    get_document_context,
)

if TYPE_CHECKING:
    from injector import Injector
    from lsprotocol import types

    from auto_type.inference import InferenceResult
else:
    # Runtime imports for things used in logic but not just types
    from lsprotocol import types

from auto_type.protocols import DiagnosticEngineProtocol, TypeAnnotationWorkflowProtocol
from auto_type.validation.mypy_validator import TypeValidationResult  # noqa: TC001

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize server
server = LanguageServer("auto-type", f"v{__version__}")


async def _refresh_settings(ls: LanguageServer, log_settings: bool = False) -> None:
    """Fetch latest client settings and apply them."""
    config = await ls.workspace_configuration_async(
        types.ConfigurationParams(items=[types.ConfigurationItem(section="autoType")])
    )
    if config and isinstance(config, list) and config[0]:
        settings = get_container().get(Settings)
        settings.update(config[0])
        if log_settings:
            logger.info(f"Initial settings: {settings}")
        return

    logger.info("No autoType settings returned from client configuration request")


async def _run_diagnostics_for_uri(ls: LanguageServer, uri: str) -> None:
    """Run diagnostics for a single URI."""
    source = get_document_context(ls, uri).source
    injector: Injector = get_container()
    diagnostic_engine: DiagnosticEngineProtocol = injector.get(DiagnosticEngineProtocol)
    await diagnostic_engine.run_diagnostics(ls, uri, source)


def _get_workflow() -> TypeAnnotationWorkflowProtocol:
    """Resolve workflow through container with protocol typing."""
    return cast(
        "TypeAnnotationWorkflowProtocol",
        cast("Any", get_container()).get(TypeAnnotationWorkflowProtocol),
    )


@server.feature(types.INITIALIZED)
async def initialized(ls: LanguageServer, params: types.InitializedParams) -> None:
    """Handle server initialization.

    Fetch initial configuration from the client.
    """
    logger.info("Server initialized, fetching configuration...")
    try:
        await _refresh_settings(ls, log_settings=True)
    except Exception as e:
        logger.error(f"Failed to fetch initial configuration: {e}")


@server.feature(types.WORKSPACE_DID_CHANGE_CONFIGURATION)
async def did_change_configuration(
    ls: LanguageServer, params: types.DidChangeConfigurationParams
) -> None:
    """Handle configuration changes from the client."""
    logger.info("Configuration changed, updating settings...")
    try:
        if isinstance(params.settings, dict) and params.settings:
            settings = get_container().get(Settings)
            settings.update(params.settings)
            return

        logger.info("Configuration payload was empty; re-fetching from client")
        await _refresh_settings(ls)
    except Exception as e:
        logger.error(f"Failed to update configuration: {e}")


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
    request_start = time.time()
    logger.info(f"Inlay hints requested for {params.text_document.uri}")

    # Check if inlay hints are enabled in settings
    container: Injector = get_container()
    settings: Settings = container.get(Settings)
    if not settings.inlay_hints_enabled:
        logger.debug("Inlay hints are disabled in settings")
        return []

    logger.info(f"Requested range: lines {params.range.start.line} to {params.range.end.line}")

    try:
        doc_context = get_document_context(server, params.text_document.uri)
        source: str = doc_context.source
        file_path: str = doc_context.file_path

        # Get workflow and helpers from container
        workflow: TypeAnnotationWorkflowProtocol = _get_workflow()
        inlay_hint_helper: InlayHintHelper = container.get(InlayHintHelper)

        try:
            # PHASE 1-2: Collect and validate
            logger.info(f"Starting type collection and validation for {file_path}")

            inference_result: InferenceResult
            validation_results: dict[str, TypeValidationResult]

            phase_start = time.time()
            inference_result, validation_results = await workflow.collect_and_validate_types(
                source,
                file_path,
            )
            phase_time = (time.time() - phase_start) * 1000
            logger.info(
                f"Phase 1 (Collection): {len(validation_results)} types "
                f"completed in {phase_time:.1f}ms"
            )

            # PHASE 3: Generate declaration hints using pre-validated types
            hints: list[types.InlayHint] = []

            for scope_id, scope_obj in inference_result.scope_tree.scopes_by_id.items():
                hints.extend(
                    inlay_hint_helper.generate_hints_for_scope(
                        scope_obj, source, validation_results, scope_id
                    )
                )

            logger.info(f"Phase 3 (Declaration Hints): {len(hints)} hints generated")

            # PHASE 4: Generate usage-site hints
            usage_hints: list[types.InlayHint] = await inlay_hint_helper.process_usage_hints(
                source=source,
                file_path=file_path,
                range_start_line=params.range.start.line,
                range_end_line=params.range.end.line,
                inference_result=inference_result,
            )
            hints.extend(usage_hints)

            total_time = (time.time() - request_start) * 1000
            logger.info(f"Generated {len(hints)} total hints in {total_time:.1f}ms.")

            return hints

        except asyncio.CancelledError:
            logger.info("Inlay hints cancelled by client")
            return []

    except Exception as e:
        elapsed = (time.time() - request_start) * 1000
        logger.error(f"Error providing inlay hints after {elapsed:.1f}ms: {e}", exc_info=True)
        return []


@server.feature(types.TEXT_DOCUMENT_DID_OPEN)
async def did_open(params: types.DidOpenTextDocumentParams) -> None:
    """Handle document open event and run diagnostics."""
    uri: str = params.text_document.uri
    logger.info(f"Document opened: {uri}")

    await _run_diagnostics_for_uri(server, uri)


@server.feature(types.TEXT_DOCUMENT_DID_CHANGE)
async def did_change(params: types.DidChangeTextDocumentParams) -> None:
    """Handle document change event with debounced diagnostics."""
    uri: str = params.text_document.uri
    logger.debug(f"Document changed: {uri}")

    # Schedule diagnostics using helper
    injector: Injector = get_container()
    diagnostic_engine: DiagnosticEngineProtocol = injector.get(DiagnosticEngineProtocol)
    diagnostic_engine.schedule_diagnostics(server, uri)


@server.feature(types.TEXT_DOCUMENT_DID_SAVE)
async def did_save(params: types.DidSaveTextDocumentParams) -> None:
    """Handle document save event and run diagnostics."""
    uri: str = params.text_document.uri
    logger.info(f"Document saved: {uri}")

    await _run_diagnostics_for_uri(server, uri)


@server.feature(types.WORKSPACE_DID_CHANGE_WATCHED_FILES)
async def did_change_watched_files(params: types.DidChangeWatchedFilesParams) -> None:
    """Handle changes to watched files (e.g., config files, imports)."""
    logger.debug(f"Watched files changed: {params.changes}")
    # For now, just log the change. Future: trigger re-inference if needed.


@server.feature("auto_type/insertType")
async def insert_type(ls: LanguageServer, params: list[Any]) -> dict[str, Any]:
    """Insert a type annotation for a variable at the cursor position.

    Custom LSP request that finds the variable at the given position, infers its type,
    and inserts the annotation. The server handles all inference and insertion logic.
    Called from VSCode when user triggers "Insert type annotation" command.

    Args:
        ls: The language server instance
        params: List with [uri, line, character] - all 0-based positions from LSP client

    Returns:
        Dict with:
        - "success": bool
        - "edits": WorkspaceEdit to apply (if success)
        - "message": str (success or error message)
    """
    request_start = time.time()

    try:
        # Debug logging to diagnose parameter wrapping
        logger.debug(f"Received insert_type params: {params!r} (type: {type(params)})")

        # Extract parameters: [uri, line, character]
        doc_context, optional = extract_uri_and_context(ls, params, num_optional=2)
        uri = doc_context.uri
        line: int = int(optional[0])
        character: int = int(optional[1])

        logger.info(f"Insert type request at {uri}:{line}:{character}")

        source: str = doc_context.source

        # Use Jedi to find the variable at the position and infer its type
        file_path = doc_context.file_path
        jedi_module = importlib.import_module("jedi")
        script = jedi_module.Script(source, path=file_path)

        # Jedi uses 1-based line numbers
        jedi_line = line + 1

        # Step 1: Use goto() to find the NAME at cursor position (variable name)
        definitions = script.goto(jedi_line, character)

        if not definitions:
            logger.debug(f"No definition found at line {jedi_line}, char {character}")
            return {
                "success": False,
                "message": "No variable or expression found at cursor position",
            }

        # Get the variable name from the definition
        definition = definitions[0]
        variable_name = definition.name

        if not variable_name:
            logger.debug(f"No variable name from definition at ({jedi_line}, {character})")
            return {
                "success": False,
                "message": "Could not determine variable name at cursor",
            }

        # Validate that we're annotating a variable, not a function/class
        if definition.type not in ("statement", "param", "instance"):
            return {
                "success": False,
                "message": f"Cannot annotate {definition.type} at cursor position",
            }

        logger.debug(f"Found variable '{variable_name}' at ({jedi_line}, {character})")

        # Use workflow for fallback inference + insertion (async)
        workflow: TypeAnnotationWorkflowProtocol = _get_workflow()

        try:
            logger.debug("Calling workflow.annotate_target_with_fallbacks...")
            workflow_start = time.time()
            annotation_result = await workflow.annotate_target_with_fallbacks(
                source=source,
                file_path=file_path,
                line_number=jedi_line,
                annotation_type="simple_variable",
                variable_name=variable_name,
            )
            modified_source = str(annotation_result["modified_source"])
            success = bool(annotation_result["insertion_success"])
            inferred_type = annotation_result.get("inferred_type")
            message = str(annotation_result.get("error_message") or "")

            workflow_time = (time.time() - workflow_start) * 1000
            logger.info(f"Workflow completed in {workflow_time:.1f}ms")

        except asyncio.CancelledError:
            logger.info("Type insertion cancelled by client")
            return {
                "success": False,
                "message": "Operation cancelled by user.",
            }

        if not success:
            logger.warning(message)
            return {
                "success": False,
                "message": message or f"Could not infer type for '{variable_name}'",
            }

        workspace_edit = build_full_document_workspace_edit(uri, source, modified_source)

        total_time = (time.time() - request_start) * 1000
        logger.info(f"Successfully created edit for {variable_name} in {total_time:.1f}ms")
        inferred_label = inferred_type if inferred_type is not None else "Unknown"
        return {
            "success": True,
            "edits": workspace_edit,
            "message": f"Inserted type annotation: {variable_name}: {inferred_label}",
        }

    except Exception as e:
        logger.error(f"Error in insert_type: {e}", exc_info=True)
        return {"success": False, "message": f"Internal error: {e!s}"}


@server.feature("auto_type/insertTypesInFile")
async def insert_types_in_file(ls: LanguageServer, params: list[Any]) -> dict[str, Any]:
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
        doc_context, _ = extract_uri_and_context(ls, params)
        uri = doc_context.uri
        logger.info(f"Insert all types request for {uri}")

        source: str = doc_context.source
        file_path: str = doc_context.file_path

        # Use workflow for insertion (async)
        workflow: TypeAnnotationWorkflowProtocol = _get_workflow()

        # Get settings
        injector: Injector = get_container()
        settings: Settings = injector.get(Settings)

        try:
            modified_source: str
            var_count: int
            func_count: int
            message: str
            modified_source, var_count, func_count, message = await workflow.insert_all_types(
                source,
                file_path,
                skip_annotated=settings.skip_annotated,
            )

            total_inserted: int = var_count + func_count
            if total_inserted == 0:
                logger.info(message)
                return {
                    "success": False,
                    "message": message,
                    "inserted_count": 0,
                    "skipped_count": 0,
                }

            workspace_edit = build_full_document_workspace_edit(uri, source, modified_source)

            logger.info(message)
            return {
                "success": True,
                "edits": workspace_edit,
                "inserted_count": total_inserted,
                "skipped_count": 0,
                "message": message,
            }

        except asyncio.CancelledError:
            logger.info("Insert all types cancelled by client")
            return {
                "success": False,
                "message": "Operation cancelled by user.",
                "inserted_count": 0,
                "skipped_count": 0,
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
async def preview_inserts(ls: LanguageServer, params: list[Any]) -> dict[str, Any]:
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
        doc_context, _ = extract_uri_and_context(ls, params)
        uri = doc_context.uri
        logger.info(f"Preview inserts request for {uri}")

        source: str = doc_context.source
        file_path: str = doc_context.file_path

        # Use workflow for preview (async)
        workflow: TypeAnnotationWorkflowProtocol = _get_workflow()
        preview: dict[str, Any] = await workflow.preview_insertions(
            source,
            file_path,
        )

        # Transform engine response to expected format
        total: int = preview.get("total_plans", 0)
        plan_details: list[dict[str, Any]] = preview.get("plan_details", [])
        will_insert: list[dict[str, Any]] = []
        for plan in plan_details:
            variable = plan.get("target") or plan.get("variable")
            type_str = plan.get("type")
            if variable is None or type_str is None:
                continue
            entry: dict[str, Any] = {"variable": variable, "type": type_str}
            if "line" in plan:
                entry["line"] = plan["line"]
            will_insert.append(entry)

        will_skip: list[dict[str, Any]] = []  # Engine doesn't track skips separately
        logger.info(f"Preview: {total} insertions, {len(will_skip)} skipped")

        return {
            "success": True,
            "will_insert": will_insert,
            "will_skip": will_skip,
            "total_changes": total,
        }

    except asyncio.CancelledError:
        logger.info("Preview inserts cancelled by client")
        return {
            "success": False,
            "will_insert": [],
            "will_skip": [],
            "total_changes": 0,
            "message": "Preview cancelled by user",
        }
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
        doc_context, optional_params = extract_uri_and_context(ls, params, num_optional=2)
        uri = doc_context.uri
        variables: list[str] | None = optional_params[0] if optional_params[0] is not None else None
        include_functions: bool = (
            bool(optional_params[1]) if optional_params[1] is not None else False
        )

        logger.info(
            f"Remove types request for {uri} "
            f"(variables={variables}, include_functions={include_functions})"
        )

        source: str = doc_context.source

        # Use workflow for removal (sync - fast CPU-bound operation)
        workflow: TypeAnnotationWorkflowProtocol = _get_workflow()
        modified_source: str
        result_info: dict[str, Any]
        modified_source, result_info = workflow.remove_types(source, variables, include_functions)

        if not result_info["success"]:
            return {
                "success": False,
                "message": "No type annotations found to remove",
                "removed_count": 0,
                "not_found": result_info.get("not_found", []),
                "skipped": result_info.get("skipped", []),
            }

        workspace_edit = build_full_document_workspace_edit(uri, source, modified_source)

        removed_count: int = result_info["removed_count"]
        not_found: list[str] = result_info.get("not_found", [])
        skipped: list[str] = result_info.get("skipped", [])

        # Build message
        if variables is None:
            message: str = f"Removed {removed_count} type annotation(s) from file."
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
        doc_context, optional_params = extract_uri_and_context(ls, params, num_optional=1)
        uri = doc_context.uri
        variables: list[str] | None = optional_params[0] if optional_params[0] is not None else None

        logger.info(f"Preview removals request for {uri} (variables={variables})")

        source: str = doc_context.source

        workflow: TypeAnnotationWorkflowProtocol = _get_workflow()

        # Get preview (sync - fast CPU-bound operation)
        preview: dict[str, Any] = workflow.preview_removals(source, variables)

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
    actions: list[types.CodeAction] = []

    injector: Injector = get_container()
    code_action_helper: CodeActionHelper = injector.get(CodeActionHelper)

    # Add "Fix wrong type" actions for diagnostics (sync)
    actions.extend(code_action_helper.get_fix_type_actions(server, params))

    # Add "Insert type" actions for unannotated variables (async)
    actions.extend(await code_action_helper.get_insert_type_actions(server, params))

    return actions


def main() -> None:
    """Start the auto-type language server."""
    logger.info("Starting auto-type language server...")
    get_container()
    server.start_io()


if __name__ == "__main__":
    main()
