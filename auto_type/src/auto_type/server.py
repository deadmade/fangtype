"""Auto-type Language Server - Interactive Python type annotation tool."""

import asyncio
import logging
from typing import Any

from lsprotocol import types
from pygls.lsp.server import LanguageServer

from auto_type.diagnostics import DiagnosticEngine
from auto_type.inference import LiteralInferenceEngine
from auto_type.insertion import InsertionEngine
from auto_type.validation import TypeValidator

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize server
server = LanguageServer("auto-type", "v0.1.0")

# Initialize inference and validation engines
inference_engine = LiteralInferenceEngine()
type_validator = TypeValidator()
insertion_engine = InsertionEngine()
diagnostic_engine = DiagnosticEngine(inference_engine)

# Global state for debouncing diagnostics
_diagnostic_timers: dict[str, asyncio.TimerHandle] = {}


@server.feature(types.TEXT_DOCUMENT_INLAY_HINT)
def inlay_hints(params: types.InlayHintParams) -> list[types.InlayHint]:
    """Provide type inlay hints for Python variables.

    This handler is called by the editor when it needs to display ghost text
    showing inferred types. It:
    1. Gets the document source code
    2. Extracts the scope (imports, class definitions)
    3. Infers types for simple variable assignments
    4. Validates each type before showing it
    5. Returns hints only for validated types

    Args:
        params: Parameters including document URI and visible range

    Returns:
        List of inlay hints to display
    """
    logger.info(f"Inlay hints requested for {params.text_document.uri}")

    try:
        # Get document from workspace
        doc = server.workspace.get_text_document(params.text_document.uri)
        source = doc.source

        # Extract scope information for validation
        scope = type_validator.extract_scope_names(source)
        logger.debug(f"Extracted scope: {scope}")

        # Get variable positions and inferred types
        positions = inference_engine.get_variable_positions(source)
        types_map = inference_engine.infer_variable_types(source)
        logger.debug(f"Inferred types: {types_map}")

        # Build hints for validated types
        hints: list[types.InlayHint] = []

        for var_name, (line, col) in positions.items():
            inferred_type = types_map.get(var_name)
            if not inferred_type:
                continue

            # Validate type before showing
            if type_validator.validate(inferred_type, scope):
                logger.debug(f"Validated type {inferred_type} for variable {var_name}")

                # Create hint positioned after variable name
                # For "x = 42", show "x: int = 42"
                hint = types.InlayHint(
                    position=types.Position(line=line, character=col + len(var_name)),
                    label=f": {inferred_type}",
                    kind=types.InlayHintKind.Type,
                    padding_left=False,
                    padding_right=False,
                )
                hints.append(hint)
            else:
                logger.debug(f"Rejected type {inferred_type} for variable {var_name}")

        logger.info(f"Returning {len(hints)} inlay hints")
        return hints

    except Exception as e:
        logger.error(f"Error providing inlay hints: {e}", exc_info=True)
        return []


@server.feature(types.TEXT_DOCUMENT_DID_OPEN)
async def did_open(params: types.DidOpenTextDocumentParams) -> None:
    """Handle document open event and run diagnostics."""
    uri = params.text_document.uri
    logger.info(f"Document opened: {uri}")
    
    # Run diagnostics on file open
    doc = server.workspace.get_text_document(uri)
    _run_diagnostics(server, uri, doc.source)


@server.feature(types.TEXT_DOCUMENT_DID_CHANGE)
async def did_change(params: types.DidChangeTextDocumentParams) -> None:
    """Handle document change event with debounced diagnostics."""
    uri = params.text_document.uri
    logger.debug(f"Document changed: {uri}")
    
    # Cancel previous timer for this document
    if uri in _diagnostic_timers:
        _diagnostic_timers[uri].cancel()
    
    # Schedule diagnostics after 500ms delay (debounced)
    loop = asyncio.get_event_loop()
    timer = loop.call_later(
        0.5,  # 500ms debounce
        lambda: _run_diagnostics_async(server, uri)
    )
    _diagnostic_timers[uri] = timer


@server.feature(types.TEXT_DOCUMENT_DID_SAVE)
async def did_save(params: types.DidSaveTextDocumentParams) -> None:
    """Handle document save event and run diagnostics."""
    uri = params.text_document.uri
    logger.info(f"Document saved: {uri}")
    
    # Run diagnostics on save
    doc = server.workspace.get_text_document(uri)
    _run_diagnostics(server, uri, doc.source)


def _run_diagnostics(ls: LanguageServer, uri: str, source: str) -> None:
    """Generate and publish diagnostics for a document.
    
    Args:
        ls: The language server instance
        uri: Document URI
        source: Document source code
    """
    try:
        diagnostics = diagnostic_engine.generate_diagnostics(source, uri)
        logger.info(f"Publishing {len(diagnostics)} diagnostics for {uri}")
        ls.text_document_publish_diagnostics(
            types.PublishDiagnosticsParams(uri=uri, diagnostics=diagnostics)
        )
    except Exception as e:
        # Log error but don't crash server
        logger.error(f"Error running diagnostics: {e}", exc_info=True)
        ls.text_document_publish_diagnostics(
            types.PublishDiagnosticsParams(uri=uri, diagnostics=[])
        )  # Clear diagnostics on error


def _run_diagnostics_async(ls: LanguageServer, uri: str) -> None:
    """Async wrapper for debounced diagnostics.
    
    Args:
        ls: The language server instance
        uri: Document URI
    """
    try:
        doc = ls.workspace.get_text_document(uri)
        _run_diagnostics(ls, uri, doc.source)
    except Exception as e:
        # Document might have been closed
        logger.debug(f"Could not run diagnostics for {uri}: {e}")


# Custom LSP requests for type insertion


@server.feature("auto_type/insertType")
def insert_type(ls: LanguageServer, params: list[Any]) -> dict[str, Any]:
    """Insert a type annotation for a single variable.

    Custom LSP request that inserts a type annotation at a specific position.
    Called from VSCode when user triggers "Insert type annotation" command.

    Args:
        ls: The language server instance
        params: List with [uri, variable_name, type_annotation]

    Returns:
        Dict with:
        - "success": bool
        - "edits": WorkspaceEdit to apply (if success)
        - "message": str (error message if not success)
    """
    try:
        uri, variable_name, type_annotation = params

        logger.info(f"Insert type request: {variable_name}: {type_annotation} in {uri}")

        # Get document
        doc = ls.workspace.get_text_document(uri)
        source = doc.source

        # Validate type before insertion
        scope = type_validator.extract_scope_names(source)
        if not type_validator.validate(type_annotation, scope):
            logger.warning(f"Type {type_annotation} failed validation")
            return {
                "success": False,
                "message": f"Type '{type_annotation}' is not valid in current scope",
            }

        # Insert type annotation
        modified_source, success = insertion_engine.insert_type(
            source, variable_name, type_annotation
        )

        if not success:
            return {
                "success": False,
                "message": f"Could not insert type for '{variable_name}' "
                "(variable not found or already annotated)",
            }

        # Create LSP WorkspaceEdit
        text_edit = types.TextEdit(
            range=types.Range(
                start=types.Position(line=0, character=0),
                end=types.Position(line=len(source.splitlines()), character=0),
            ),
            new_text=modified_source,
        )

        workspace_edit = types.WorkspaceEdit(
            changes={uri: [text_edit]}
        )

        logger.info(f"Successfully created edit for {variable_name}")
        return {
            "success": True,
            "edits": workspace_edit,
        }

    except Exception as e:
        logger.error(f"Error in insert_type: {e}", exc_info=True)
        return {
            "success": False,
            "message": f"Internal error: {str(e)}",
        }


@server.feature("auto_type/insertTypesInFile")
def insert_types_in_file(ls: LanguageServer, params: Any) -> dict[str, Any]:
    """Insert type annotations for all inferred types in a file.

    Custom LSP request that inserts all inferred type annotations at once.
    Called from VSCode when user triggers "Insert all types" command.

    Args:
        ls: The language server instance
        params: List with [uri]

    Returns:
        Dict with:
        - "success": bool
        - "edits": WorkspaceEdit to apply (if success)
        - "inserted_count": int
        - "skipped_count": int
        - "message": str
    """
    try:
        # Handle different parameter structures (defensive extraction)
        uri: str
        if isinstance(params, str):
            # Direct string (unwrapped)
            uri = params
        elif isinstance(params, list) and len(params) > 0:
            # Check if double-wrapped: [[uri]] or single-wrapped: [uri]
            if isinstance(params[0], list) and len(params[0]) > 0:
                # Double-wrapped: [[uri]]
                uri = str(params[0][0])
                logger.warning(f"Received double-wrapped parameters: {params!r}")
            else:
                # Single-wrapped: [uri]
                uri = str(params[0])
        else:
            raise ValueError(f"Invalid params structure: {params!r}")

        logger.info(f"Insert all types request for {uri}")

        # Get document
        doc = ls.workspace.get_text_document(uri)
        source = doc.source

        # Get all inferred types
        types_map = inference_engine.infer_variable_types(source)
        logger.info(f"Found {len(types_map)} inferred types")

        if not types_map:
            return {
                "success": False,
                "message": "No types to insert (no variables found)",
                "inserted_count": 0,
                "skipped_count": 0,
            }

        # Validate all types before insertion
        scope = type_validator.extract_scope_names(source)
        validated_types = {
            var: type_str
            for var, type_str in types_map.items()
            if type_validator.validate(type_str, scope)
        }

        invalid_count = len(types_map) - len(validated_types)
        if invalid_count > 0:
            logger.warning(f"Filtered out {invalid_count} invalid types")

        if not validated_types:
            return {
                "success": False,
                "message": "No valid types to insert (all types failed validation)",
                "inserted_count": 0,
                "skipped_count": len(types_map),
            }

        # Insert all validated types
        modified_source, result_info = insertion_engine.insert_types_bulk(
            source, validated_types, skip_annotated=True
        )

        if not result_info["success"]:
            return {
                "success": False,
                "message": "Failed to insert types",
                "inserted_count": 0,
                "skipped_count": len(types_map),
            }

        # Create LSP WorkspaceEdit
        text_edit = types.TextEdit(
            range=types.Range(
                start=types.Position(line=0, character=0),
                end=types.Position(line=len(source.splitlines()), character=0),
            ),
            new_text=modified_source,
        )

        workspace_edit = types.WorkspaceEdit(
            changes={uri: [text_edit]}
        )

        message = (
            f"Inserted {result_info['inserted_count']} type annotations. "
            f"Skipped {len(result_info['skipped'])} already-annotated variables."
        )

        logger.info(message)
        return {
            "success": True,
            "edits": workspace_edit,
            "inserted_count": result_info["inserted_count"],
            "skipped_count": len(result_info["skipped"]),
            "message": message,
        }

    except Exception as e:
        logger.error(f"Error in insert_types_in_file: {e}", exc_info=True)
        return {
            "success": False,
            "message": f"Internal error: {str(e)}",
            "inserted_count": 0,
            "skipped_count": 0,
        }


@server.feature("auto_type/previewInserts")
def preview_inserts(ls: LanguageServer, params: Any) -> dict[str, Any]:
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
        # Handle different parameter structures (defensive extraction)
        uri: str
        if isinstance(params, str):
            # Direct string (unwrapped)
            uri = params
        elif isinstance(params, list) and len(params) > 0:
            # Check if double-wrapped: [[uri]] or single-wrapped: [uri]
            if isinstance(params[0], list) and len(params[0]) > 0:
                # Double-wrapped: [[uri]]
                uri = str(params[0][0])
                logger.warning(f"Received double-wrapped parameters: {params!r}")
            else:
                # Single-wrapped: [uri]
                uri = str(params[0])
        else:
            raise ValueError(f"Invalid params structure: {params!r}")

        logger.info(f"Preview inserts request for {uri}")

        # Get document
        doc = ls.workspace.get_text_document(uri)
        source = doc.source

        # Get all inferred types
        types_map = inference_engine.infer_variable_types(source)

        if not types_map:
            return {
                "success": True,
                "will_insert": [],
                "will_skip": [],
                "total_changes": 0,
                "message": "No types found to insert",
            }

        # Validate types
        scope = type_validator.extract_scope_names(source)
        validated_types = {
            var: type_str
            for var, type_str in types_map.items()
            if type_validator.validate(type_str, scope)
        }

        # Get preview
        preview = insertion_engine.preview_insertions(source, validated_types)

        logger.info(
            f"Preview: {preview['total_changes']} insertions, "
            f"{len(preview['will_skip'])} skipped"
        )

        return preview

    except Exception as e:
        logger.error(f"Error in preview_inserts: {e}", exc_info=True)
        return {
            "success": False,
            "will_insert": [],
            "will_skip": [],
            "total_changes": 0,
            "message": f"Internal error: {str(e)}",
            }


@server.feature("auto_type/removeTypesInFile")
def remove_types_in_file(ls: LanguageServer, params: Any) -> dict[str, Any]:
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
        # Handle different parameter structures (defensive extraction)
        uri: str
        variables: list[str] | None = None
        include_functions: bool = False

        if isinstance(params, str):
            # Direct string (unwrapped) - just URI
            uri = params
        elif isinstance(params, list) and len(params) > 0:
            # Check for different wrapping levels
            if isinstance(params[0], list) and len(params[0]) > 0:
                # Double-wrapped: [[uri, ...]]
                inner = params[0]
                uri = str(inner[0])
                if len(inner) > 1:
                    variables = inner[1] if inner[1] is not None else None
                if len(inner) > 2:
                    include_functions = bool(inner[2])
                logger.warning(f"Received double-wrapped parameters: {params!r}")
            else:
                # Single-wrapped: [uri, ...]
                uri = str(params[0])
                if len(params) > 1:
                    variables = params[1] if params[1] is not None else None
                if len(params) > 2:
                    include_functions = bool(params[2])
        else:
            raise ValueError(f"Invalid params structure: {params!r}")

        logger.info(
            f"Remove types request for {uri} "
            f"(variables={variables}, include_functions={include_functions})"
        )

        # Get document
        doc = ls.workspace.get_text_document(uri)
        source = doc.source

        # Remove type annotations
        modified_source, result_info = insertion_engine.remove_types_bulk(
            source, variables, include_functions
        )

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

        workspace_edit = types.WorkspaceEdit(
            changes={uri: [text_edit]}
        )

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
            "message": f"Internal error: {str(e)}",
            "removed_count": 0,
            "not_found": [],
            "skipped": [],
        }


@server.feature("auto_type/previewRemovals")
def preview_removals(ls: LanguageServer, params: Any) -> dict[str, Any]:
    """Preview what type annotations would be removed without modifying code.

    Custom LSP request that shows a preview of what removals would be made.
    Used for the bulk removal preview dialog.

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
        # Handle different parameter structures (defensive extraction)
        uri: str
        variables: list[str] | None = None

        if isinstance(params, str):
            # Direct string (unwrapped)
            uri = params
        elif isinstance(params, list) and len(params) > 0:
            # Check if double-wrapped: [[uri, ...]] or single-wrapped: [uri, ...]
            if isinstance(params[0], list) and len(params[0]) > 0:
                # Double-wrapped: [[uri, variables]]
                inner = params[0]
                uri = str(inner[0])
                if len(inner) > 1:
                    variables = inner[1] if inner[1] is not None else None
                logger.warning(f"Received double-wrapped parameters: {params!r}")
            else:
                # Single-wrapped: [uri, variables]
                uri = str(params[0])
                if len(params) > 1:
                    variables = params[1] if params[1] is not None else None
        else:
            raise ValueError(f"Invalid params structure: {params!r}")

        logger.info(
            f"Preview removals request for {uri} "
            f"(variables={variables})"
        )

        # Get document
        doc = ls.workspace.get_text_document(uri)
        source = doc.source

        # Get preview
        preview = insertion_engine.preview_removals(source, variables)

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
            "message": f"Internal error: {str(e)}",
        }


@server.feature(types.TEXT_DOCUMENT_CODE_ACTION)
def code_actions(params: types.CodeActionParams) -> list[types.CodeAction]:
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
    
    # Add "Fix wrong type" actions for diagnostics
    actions.extend(_get_fix_type_actions(params))
    
    # Add "Insert type" actions for unannotated variables
    actions.extend(_get_insert_type_actions(params))
    
    return actions


def _get_fix_type_actions(params: types.CodeActionParams) -> list[types.CodeAction]:
    """Generate 'Change type to...' actions for type mismatch diagnostics.
    
    Args:
        params: Code action parameters including diagnostics
        
    Returns:
        List of code actions to fix wrong types
    """
    actions = []
    
    try:
        uri = params.text_document.uri
        doc = server.workspace.get_text_document(uri)
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
            annotation = diagnostic.data.get("annotation")
            
            if not inferred_type or not var_name:
                continue
            
            # Use InsertionEngine to replace the type
            modified_source, success = insertion_engine.replace_type(
                source, var_name, inferred_type
            )
            
            if not success:
                logger.warning(f"Failed to create replacement for {var_name}")
                continue
            
            # Create workspace edit
            text_edit = types.TextEdit(
                range=types.Range(
                    start=types.Position(line=0, character=0),
                    end=types.Position(line=len(source.splitlines()), character=0),
                ),
                new_text=modified_source,
            )
            
            workspace_edit = types.WorkspaceEdit(
                changes={uri: [text_edit]}
            )
            
            # Create "Change type to..." action
            action = types.CodeAction(
                title=f"Change type to '{inferred_type}'",
                kind=types.CodeActionKind.QuickFix,
                edit=workspace_edit,
                diagnostics=[diagnostic],  # Link to diagnostic
            )
            
            actions.append(action)
            
            # Also offer "Remove type annotation" as alternative
            remove_action = _create_remove_type_action(
                uri, source, var_name, diagnostic
            )
            if remove_action:
                actions.append(remove_action)
    
    except Exception as e:
        logger.error(f"Error generating fix type actions: {e}", exc_info=True)
    
    return actions


def _create_remove_type_action(
    uri: str, source: str, var_name: str, diagnostic: types.Diagnostic
) -> types.CodeAction | None:
    """Create a code action to remove a type annotation.
    
    Args:
        uri: Document URI
        source: Document source code
        var_name: Variable name
        diagnostic: The diagnostic this action fixes
        
    Returns:
        Code action to remove type, or None if creation failed
    """
    try:
        modified_source, success = insertion_engine.remove_type(source, var_name)
        
        if not success:
            return None
        
        text_edit = types.TextEdit(
            range=types.Range(
                start=types.Position(line=0, character=0),
                end=types.Position(line=len(source.splitlines()), character=0),
            ),
            new_text=modified_source,
        )
        
        workspace_edit = types.WorkspaceEdit(
            changes={uri: [text_edit]}
        )
        
        return types.CodeAction(
            title="Remove type annotation",
            kind=types.CodeActionKind.QuickFix,
            edit=workspace_edit,
            diagnostics=[diagnostic],
        )
    except Exception as e:
        logger.error(f"Error creating remove type action: {e}", exc_info=True)
        return None


def _get_insert_type_actions(params: types.CodeActionParams) -> list[types.CodeAction]:
    """Generate 'Insert type annotation' actions for unannotated variables.
    
    Args:
        params: Code action parameters
        
    Returns:
        List of code actions to insert types
    """
    try:
        uri = params.text_document.uri
        doc = server.workspace.get_text_document(uri)
        source = doc.source

        # Get the line where the code action was requested
        start_line = params.range.start.line
        line_content = source.splitlines()[start_line] if start_line < len(source.splitlines()) else ""

        # Check if this line has a variable assignment
        # Simple heuristic: look for "var_name = " pattern
        import re
        match = re.match(r'^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*', line_content)
        
        if not match:
            return []

        var_name = match.group(1)

        # Check if variable already has annotation
        if ":" in line_content.split("=")[0]:
            # Already annotated, don't offer action
            return []

        # Get inferred type for this variable
        types_map = inference_engine.infer_variable_types(source)
        inferred_type = types_map.get(var_name)

        if not inferred_type:
            return []

        # Validate the type
        scope = type_validator.extract_scope_names(source)
        if not type_validator.validate(inferred_type, scope):
            return []

        # Insert the type annotation and create a WorkspaceEdit
        modified_source, success = insertion_engine.insert_type(
            source, var_name, inferred_type
        )

        if not success:
            logger.warning(f"Failed to create edit for {var_name}: {inferred_type}")
            return []

        # Create LSP WorkspaceEdit with the modified source
        text_edit = types.TextEdit(
            range=types.Range(
                start=types.Position(line=0, character=0),
                end=types.Position(line=len(source.splitlines()), character=0),
            ),
            new_text=modified_source,
        )

        workspace_edit = types.WorkspaceEdit(
            changes={uri: [text_edit]}
        )

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


def main() -> None:
    """Start the auto-type language server."""
    logger.info("Starting auto-type language server...")
    server.start_io()


if __name__ == "__main__":
    main()
