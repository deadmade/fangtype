"""Auto-type Language Server - Interactive Python type annotation tool."""

import asyncio
import logging
import time
from typing import Any

from lsprotocol import types
from pygls.lsp.server import LanguageServer

from auto_type.diagnostics import DiagnosticEngine
from auto_type.inference import UnifiedInferenceEngine
from auto_type.insertion import InsertionEngine
from auto_type.validation import MypyTypeValidator

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize server
server = LanguageServer("auto-type", "v0.1.0")

# Initialize inference and validation engines
unified_inference_engine = UnifiedInferenceEngine()
mypy_validator = MypyTypeValidator()
insertion_engine = InsertionEngine()
diagnostic_engine = DiagnosticEngine(mypy_validator)

# Global state for debouncing diagnostics
_diagnostic_timers: dict[str, asyncio.TimerHandle] = {}


def _generate_hints_for_scope(
    scope: Any, source: str, validated_types: dict[str, str], scope_id: str
) -> list[types.InlayHint]:
    """Generate inlay hints for all variables/parameters/returns in a scope.

    Uses the scope tree directly - no manual AST walking needed!

    Args:
        scope: Scope object containing variables, parameters, and return type
        source: Source code (needed for return type hint positioning)
        validated_types: Pre-validated types dict with keys like "scope_id.category.name"
        scope_id: ID of this scope for constructing validated_types keys

    Returns:
        List of inlay hints for this scope
    """
    import ast

    from auto_type.analysis.types import ScopeType

    hints: list[types.InlayHint] = []

    # Generate hints for local variables
    for var_name, type_info in scope.variables.items():
        # Skip if type is Unknown or invalid position
        if type_info.type_str == "Unknown":
            continue
        if type_info.line < 0 or type_info.col < 0:
            logger.warning(
                f"Invalid position for variable {var_name}: "
                f"line={type_info.line}, col={type_info.col}"
            )
            continue

        # Check if type was validated
        validation_key = f"{scope_id}.var.{var_name}"
        if validation_key in validated_types:
            hint = types.InlayHint(
                position=types.Position(
                    line=type_info.line, character=type_info.col + len(var_name)
                ),
                label=f" {type_info.type_str}",
                kind=types.InlayHintKind.Type,
                padding_left=False,
                padding_right=False,
            )
            hints.append(hint)

    # Generate hints for parameters (function scopes only)
    if scope.scope_type == ScopeType.FUNCTION:
        # Get function AST node to check for existing annotations
        func_node = scope.ast_node
        if func_node and isinstance(func_node, ast.FunctionDef | ast.AsyncFunctionDef):
            # Build map of parameter names to annotations
            annotated_params = {arg.arg for arg in func_node.args.args if arg.annotation}

            for param_name, type_info in scope.parameters.items():
                # Skip if already annotated
                if param_name in annotated_params:
                    continue

                # Skip if type is Unknown or invalid position
                if type_info.type_str == "Unknown":
                    continue
                if type_info.line < 0 or type_info.col < 0:
                    logger.warning(
                        f"Invalid position for parameter {param_name}: "
                        f"line={type_info.line}, col={type_info.col}"
                    )
                    continue

                # Check if type was validated
                validation_key = f"{scope_id}.param.{param_name}"
                if validation_key in validated_types:
                    hint = types.InlayHint(
                        position=types.Position(
                            line=type_info.line, character=type_info.col + len(param_name)
                        ),
                        label=f": {type_info.type_str}",
                        kind=types.InlayHintKind.Type,
                        padding_left=False,
                        padding_right=False,
                    )
                    hints.append(hint)

            # Generate return type hint
            validation_key = f"{scope_id}.return"
            if (
                scope.return_type
                and scope.return_type.type_str != "Unknown"
                and not func_node.returns
                and validation_key in validated_types
            ):
                # Find closing paren position
                func_line = func_node.lineno - 1
                lines = source.splitlines()
                if func_line < len(lines):
                    line_text = lines[func_line]
                    # Find closing paren
                    close_paren_pos = line_text.rfind(")")
                    if close_paren_pos != -1:
                        hint = types.InlayHint(
                            position=types.Position(line=func_line, character=close_paren_pos + 1),
                            label=f" -> {scope.return_type.type_str}",
                            kind=types.InlayHintKind.Type,
                            padding_left=False,
                            padding_right=False,
                        )
                        hints.append(hint)

    return hints


@server.feature(types.TEXT_DOCUMENT_INLAY_HINT)
def inlay_hints(params: types.InlayHintParams) -> list[types.InlayHint]:
    """Provide type inlay hints for Python variables.

    This handler is called by the editor when it needs to display ghost text
    showing inferred types. It:
    1. Gets the document source code
    2. Performs comprehensive type inference (literal + contextual + propagation)
    3. Generates hints for:
       - Module-level variables
       - Function parameters
       - Function return types
       - Local variables within functions
    4. Validates each type before showing it
    5. Returns hints only for validated types

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

        # Perform unified type inference
        inference_result = unified_inference_engine.infer_types(source)
        logger.debug(f"Inferred types for {len(inference_result.scope_tree.scopes_by_id)} scopes")

        # PHASE 1: Collect all types to validate from all scopes
        from auto_type.analysis.types import ScopeType

        start_collection = time.time()
        all_types_to_validate: dict[str, str] = {}

        for scope_id, scope_obj in inference_result.scope_tree.scopes_by_id.items():
            # Collect local variables
            for var_name, type_info in scope_obj.variables.items():
                if type_info.type_str != "Unknown":
                    # Use unique key: scope_id.category.name
                    key = f"{scope_id}.var.{var_name}"
                    all_types_to_validate[key] = type_info.type_str

            # Collect function parameters and return types
            if scope_obj.scope_type == ScopeType.FUNCTION:
                # Parameters
                for param_name, type_info in scope_obj.parameters.items():
                    if type_info.type_str != "Unknown":
                        key = f"{scope_id}.param.{param_name}"
                        all_types_to_validate[key] = type_info.type_str

                # Return type
                if scope_obj.return_type and scope_obj.return_type.type_str != "Unknown":
                    key = f"{scope_id}.return"
                    all_types_to_validate[key] = scope_obj.return_type.type_str

        collection_time = time.time() - start_collection
        logger.info(
            f"Phase 1 (Collection): {len(all_types_to_validate)} types collected "
            f"in {collection_time:.3f}s"
        )

        # PHASE 2: Batch validate all types at once (single mypy call!)
        start_validation = time.time()
        validated_types = mypy_validator.validate_bulk(all_types_to_validate, source)
        validation_time = time.time() - start_validation

        invalid_count = len(all_types_to_validate) - len(validated_types)
        logger.info(
            f"Phase 2 (Validation): {len(validated_types)}/"
            f"{len(all_types_to_validate)} types validated "
            f"in {validation_time:.3f}s ({invalid_count} filtered)"
        )

        # PHASE 3: Generate hints using pre-validated types
        start_generation = time.time()
        hints: list[types.InlayHint] = []

        for scope_id, scope_obj in inference_result.scope_tree.scopes_by_id.items():
            hints.extend(_generate_hints_for_scope(scope_obj, source, validated_types, scope_id))

        generation_time = time.time() - start_generation
        logger.info(f"Phase 3 (Generation): {len(hints)} hints generated in {generation_time:.3f}s")

        total_time = collection_time + validation_time + generation_time
        logger.info(
            f"Total inlay hint time: {total_time:.3f}s "
            f"(collection: {collection_time:.3f}s, validation: {validation_time:.3f}s, "
            f"generation: {generation_time:.3f}s)"
        )

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
        lambda: _run_diagnostics_async(server, uri),
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

        # Validate type before insertion using mypy
        valid, error_msg = mypy_validator.validate_insertion(source, variable_name, type_annotation)
        if not valid:
            logger.warning(f"Type {type_annotation} failed validation: {error_msg}")
            return {
                "success": False,
                "message": f"Type validation failed: {error_msg}",
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

        workspace_edit = types.WorkspaceEdit(changes={uri: [text_edit]})

        logger.info(f"Successfully created edit for {variable_name}")
        return {
            "success": True,
            "edits": workspace_edit,
        }

    except Exception as e:
        logger.error(f"Error in insert_type: {e}", exc_info=True)
        return {
            "success": False,
            "message": f"Internal error: {e!s}",
        }


@server.feature("auto_type/insertTypesInFile")
def insert_types_in_file(ls: LanguageServer, params: Any) -> dict[str, Any]:
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

        # Get all inferred types (variables + functions)
        inference_result = unified_inference_engine.infer_types(source)
        all_insertable = inference_result.get_all_insertable_types()

        module_vars = all_insertable["module_vars"]
        functions = all_insertable["functions"]

        logger.info(
            f"Found {len(module_vars)} module variables and {len(functions)} functions with types"
        )

        if not module_vars and not functions:
            return {
                "success": False,
                "message": "No types to insert (no variables or functions found)",
                "inserted_count": 0,
                "skipped_count": 0,
            }

        # Validate all types before insertion using mypy
        # Validate module-level variable types
        validated_vars = mypy_validator.validate_bulk(module_vars, source)

        # Validate function types
        validated_functions = mypy_validator.validate_function_signatures(functions, source)

        invalid_count = (
            len(module_vars) - len(validated_vars) + len(functions) - len(validated_functions)
        )
        if invalid_count > 0:
            logger.warning(f"Filtered out {invalid_count} invalid types")

        if not validated_vars and not validated_functions:
            return {
                "success": False,
                "message": "No valid types to insert (all types failed validation)",
                "inserted_count": 0,
                "skipped_count": len(module_vars) + len(functions),
            }

        # Insert module-level variable types
        modified_source = source
        var_insert_count = 0
        if validated_vars:
            modified_source, var_result = insertion_engine.insert_types_bulk(
                modified_source, validated_vars, skip_annotated=True
            )
            if var_result["success"]:
                var_insert_count = var_result["inserted_count"]

        # Insert function signatures
        func_insert_count = 0
        if validated_functions:
            modified_source, func_result = insertion_engine.insert_function_signatures(
                modified_source, validated_functions, skip_annotated=True
            )
            if func_result["success"]:
                func_insert_count = func_result["modified_count"]

        total_inserted = var_insert_count + func_insert_count

        if total_inserted == 0:
            return {
                "success": False,
                "message": "No types inserted (all items already annotated)",
                "inserted_count": 0,
                "skipped_count": len(validated_vars) + len(validated_functions),
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

        message = (
            f"Inserted {total_inserted} type annotations "
            f"({var_insert_count} variables, {func_insert_count} functions). "
        )

        logger.info(message)
        return {
            "success": True,
            "edits": workspace_edit,
            "inserted_count": total_inserted,
            "skipped_count": 0,  # Not tracking skipped in this implementation
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
        types_map = unified_inference_engine.infer_variable_types(source)

        if not types_map:
            return {
                "success": True,
                "will_insert": [],
                "will_skip": [],
                "total_changes": 0,
                "message": "No types found to insert",
            }

        # Validate types using mypy
        validated_types = mypy_validator.validate_bulk(types_map, source)

        # Get preview
        preview = insertion_engine.preview_insertions(source, validated_types)

        logger.info(
            f"Preview: {preview['total_changes']} insertions, {len(preview['will_skip'])} skipped"
        )

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

        logger.info(f"Preview removals request for {uri} (variables={variables})")

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
            "message": f"Internal error: {e!s}",
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
            remove_action = _create_remove_type_action(uri, source, var_name, diagnostic)
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

        workspace_edit = types.WorkspaceEdit(changes={uri: [text_edit]})

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
        line_content = (
            source.splitlines()[start_line] if start_line < len(source.splitlines()) else ""
        )

        # Check if this line has a variable assignment
        # Simple heuristic: look for "var_name = " pattern
        import re

        match = re.match(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*", line_content)

        if not match:
            return []

        var_name = match.group(1)

        # Check if variable already has annotation
        if ":" in line_content.split("=")[0]:
            # Already annotated, don't offer action
            return []

        # Get inferred type for this variable
        types_map = unified_inference_engine.infer_variable_types(source)
        inferred_type = types_map.get(var_name)

        if not inferred_type:
            return []

        # Validate the type using mypy
        if not mypy_validator.validate(inferred_type, source):
            return []

        # Insert the type annotation and create a WorkspaceEdit
        modified_source, success = insertion_engine.insert_type(source, var_name, inferred_type)

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


def main() -> None:
    """Start the auto-type language server."""
    logger.info("Starting auto-type language server...")
    server.start_io()


if __name__ == "__main__":
    main()
