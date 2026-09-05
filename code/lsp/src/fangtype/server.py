"""Auto-type Language Server - Interactive Python type annotation tool."""

from __future__ import annotations

import asyncio
import functools
import inspect
import logging
import os
import time
from typing import TYPE_CHECKING, Any, cast

from lsprotocol import types
from pygls.lsp.server import LanguageServer

from fangtype import __version__
from fangtype.cancellation import CancellationToken
from fangtype.container import (
    build_container,
    resolve_engine_name,
)
from fangtype.utils import (
    CodeActionHelper,
    DocumentCache,
    InlayHintHelper,
    Settings,
    build_full_document_workspace_edit,
    extract_uri_and_context,
    get_document_context,
)

if TYPE_CHECKING:
    from injector import Injector

    from fangtype.inference import InferenceResult

from fangtype.protocols import (
    DiagnosticEngineProtocol,
    TypeValidatorProtocol,
)
from fangtype.workflow import TypeAnnotationWorkflow

_LOG_LEVEL = getattr(
    logging, os.environ.get("FANGTYPE_LOG_LEVEL", "WARNING").upper(), logging.WARNING
)
logging.basicConfig(level=_LOG_LEVEL, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def _select_settings_payload(opts: Any) -> dict[str, Any] | None:
    """Pick settings from initOptions: {settings} first, globalSettings fallback, else None."""
    if not isinstance(opts, dict):
        return None

    settings = opts.get("settings")
    if isinstance(settings, dict):
        return settings
    if isinstance(settings, list) and settings and isinstance(settings[0], dict):
        return settings[0]

    global_settings = opts.get("globalSettings")
    if isinstance(global_settings, dict):
        return global_settings

    return opts or None


def _build_declaration_hints(
    helper: InlayHintHelper,
    inference_result: InferenceResult,
    source: str,
) -> list[types.InlayHint]:
    """Declaration-site inlay hints for every inferred type, across all scopes."""
    hints: list[types.InlayHint] = []
    for scope_obj in inference_result.scope_tree.scopes_by_id.values():
        hints.extend(helper.generate_hints_for_scope(scope_obj, source))
    return hints


class FangtypeServer(LanguageServer):
    """pygls server + all LSP handlers; DI-wired by from_container; __init__ registers handlers."""

    def __init__(
        self,
        *,
        workflow: TypeAnnotationWorkflow,
        diagnostics: DiagnosticEngineProtocol,
        code_action_helper: CodeActionHelper,
        inlay_hints_helper: InlayHintHelper,
        settings: Settings,
        validator: TypeValidatorProtocol,
        document_cache: DocumentCache,
    ) -> None:
        super().__init__("fangtype", f"v{__version__}")
        self.workflow = workflow
        self.diagnostics = diagnostics
        self.code_action_helper = code_action_helper
        self.inlay_hints_helper = inlay_hints_helper
        self.settings = settings
        self.validator = validator
        self.document_cache = document_cache
        self._register_features()

    @classmethod
    def from_container(cls, injector: Injector) -> FangtypeServer:
        """Build a server, resolving each dependency from the DI container."""
        return cls(
            workflow=injector.get(TypeAnnotationWorkflow),
            diagnostics=injector.get(DiagnosticEngineProtocol),
            code_action_helper=injector.get(CodeActionHelper),
            inlay_hints_helper=injector.get(InlayHintHelper),
            settings=injector.get(Settings),
            validator=injector.get(TypeValidatorProtocol),
            document_cache=injector.get(DocumentCache),
        )

    def _register_features(self) -> None:
        """Register every handler method with pygls' feature manager."""
        self._register(types.INITIALIZE, self.initialize)
        self._register(types.INITIALIZED, self.initialized)
        self._register(types.WORKSPACE_DID_CHANGE_CONFIGURATION, self.did_change_configuration)
        self._register(types.TEXT_DOCUMENT_INLAY_HINT, self.inlay_hints)
        self._register(types.TEXT_DOCUMENT_DID_OPEN, self.did_open)
        self._register(types.TEXT_DOCUMENT_DID_CHANGE, self.did_change)
        self._register(types.TEXT_DOCUMENT_DID_SAVE, self.did_save)
        self._register(types.TEXT_DOCUMENT_DID_CLOSE, self.did_close)
        self._register("fangtype/insertType", self.insert_type)
        self._register("fangtype/insertTypesInFile", self.insert_types_in_file)
        self._register("fangtype/removeTypesInFile", self.remove_types_in_file)
        self._register("fangtype/previewRemovals", self.preview_removals)
        self._register(types.TEXT_DOCUMENT_CODE_ACTION, self.code_actions)
        self._register(types.SHUTDOWN, self.on_shutdown)

    def _register(self, name: str, method: Any) -> None:
        """Register handler under LSP name; wrap in plain fn as setattr rejects bound methods."""
        if inspect.iscoroutinefunction(method):

            @functools.wraps(method)
            async def handler(*args: Any, **kwargs: Any) -> Any:
                return await method(*args, **kwargs)

        else:

            @functools.wraps(method)
            def handler(*args: Any, **kwargs: Any) -> Any:
                return method(*args, **kwargs)

        self.feature(name)(handler)

    async def _request_inlay_refresh(self) -> None:
        """Ask the client to re-pull inlay hints; best-effort, never breaks a lifecycle handler."""
        try:
            await self.workspace_inlay_hint_refresh_async(None)
        except Exception as e:
            logger.debug(f"inlay hint refresh unavailable or failed: {e}")

    async def _run_diagnostics_for_uri(self, uri: str) -> None:
        """Run diagnostics for a URI, then ask the client to re-pull inlay hints."""
        source = get_document_context(self, uri).source
        await self.diagnostics.run_diagnostics(self, uri, source)
        await self._request_inlay_refresh()

    # ---- (1) Lifecycle -----------------------------------------------------

    async def initialize(self, params: types.InitializeParams) -> None:
        """Apply settings pushed by the client via ``initializationOptions``."""
        opts = params.initialization_options
        if isinstance(opts, dict):
            # Interpreter/root ride beside `settings`, not in it: managed venv stays project-aware.
            self.settings.update_launch_context(opts)

        payload: dict[str, Any] | None = _select_settings_payload(opts)
        if payload is None:
            logger.info("No initializationOptions settings; keeping current settings")
            return

        try:
            self.settings.update(payload)
            logger.info(f"Applied settings from initializationOptions: {self.settings}")
        except Exception as e:
            logger.error(f"Failed to apply initializationOptions settings: {e}")

    async def initialized(self, params: types.InitializedParams) -> None:
        """Handle server initialization."""
        logger.info("Server initialized. Have fun coding :)")

    async def did_change_configuration(self, params: types.DidChangeConfigurationParams) -> None:
        """Apply settings pushed by the client via ``didChangeConfiguration``."""
        payload: dict[str, Any] | None = (
            _select_settings_payload({"settings": params.settings}) if params.settings else None
        )
        if payload is None:
            logger.info("No didChangeConfiguration settings; keeping current settings")
            return

        try:
            self.settings.update(payload)
            logger.info(f"Applied settings from didChangeConfiguration: {self.settings}")
        except Exception as e:
            logger.error(f"Failed to apply didChangeConfiguration settings: {e}")

    # ---- (2) Inlay hints ---------------------------------------------------

    async def inlay_hints(self, params: types.InlayHintParams) -> list[types.InlayHint]:
        """Provide type inlay hints for Python variables."""
        request_start = time.time()
        logger.info(f"Inlay hints requested for {params.text_document.uri}")

        logger.info(f"Requested range: lines {params.range.start.line} to {params.range.end.line}")

        cancel_token = CancellationToken()

        try:
            doc_context = get_document_context(self, params.text_document.uri)
            source: str = doc_context.source
            file_path: str = doc_context.file_path

            workflow = self.workflow
            inlay_hint_helper = self.inlay_hints_helper

            try:
                # 1. Infer all types (off-thread, in the workflow).
                inference_result = await workflow.collect_types(
                    source,
                    file_path,
                    cancel_token=cancel_token,
                    uri=doc_context.uri,
                    version=doc_context.version,
                )
                # 2. Declaration-site hints (LSP InlayHint objects built here, server-side).
                hints: list[types.InlayHint] = _build_declaration_hints(
                    inlay_hint_helper, inference_result, source
                )
                # 3. Usage-site hints across the requested range.
                hints.extend(
                    await inlay_hint_helper.process_usage_hints(
                        source=source,
                        file_path=file_path,
                        range_start_line=params.range.start.line,
                        range_end_line=params.range.end.line,
                        inference_result=inference_result,
                        cancel_token=cancel_token,
                    )
                )
                total_time = (time.time() - request_start) * 1000
                logger.info(f"Generated {len(hints)} total hints in {total_time:.1f}ms.")
                return hints

            except asyncio.CancelledError:
                cancel_token.cancel()
                logger.info("Inlay hints cancelled by client")
                return []

        except Exception as e:
            elapsed = (time.time() - request_start) * 1000
            logger.error(f"Error providing inlay hints after {elapsed:.1f}ms: {e}", exc_info=True)
            return []

    # ---- (3) Document sync -------------------------------------------------

    async def did_open(self, params: types.DidOpenTextDocumentParams) -> None:
        """Handle document open event and run diagnostics."""
        uri: str = params.text_document.uri
        logger.info(f"Document opened: {uri}")

        await self._run_diagnostics_for_uri(uri)

    async def did_change(self, params: types.DidChangeTextDocumentParams) -> None:
        """Handle document change event with debounced diagnostics."""
        uri: str = params.text_document.uri
        logger.debug(f"Document changed: {uri}")

        # Drop superseded inference (memory hygiene; bumped version already makes it unreachable).
        self.document_cache.evict(uri)
        self.diagnostics.schedule_diagnostics(self, uri)
        # Refresh inlay hints now, not only after the debounced diagnostics: an applied insert edit
        # produces exactly this change, and VSCode's own re-pull can get cancelled and stick. Cheap
        # — the client middleware dedupes it onto the in-flight re-pull for this same version.
        await self._request_inlay_refresh()

    async def did_save(self, params: types.DidSaveTextDocumentParams) -> None:
        """Handle document save event and run diagnostics."""
        uri: str = params.text_document.uri
        logger.info(f"Document saved: {uri}")

        await self._run_diagnostics_for_uri(uri)

    async def did_close(self, params: types.DidCloseTextDocumentParams) -> None:
        """Handle document close event, cancelling any pending debounced diagnostics."""
        uri: str = params.text_document.uri
        logger.info(f"Document closed: {uri}")

        self.document_cache.evict(uri)
        self.diagnostics.cancel_pending(uri)

    # ---- (4) Custom fangtype/* commands ------------------------------------

    async def insert_type(self, ls: LanguageServer, params: list[Any]) -> dict[str, Any]:
        """Insert a type annotation for the identifier at the cursor position."""
        request_start = time.time()

        try:
            # Extract parameters: [uri, line, character] (line/character are 0-based)
            doc_context, optional = extract_uri_and_context(ls, params, num_optional=2)
            uri = doc_context.uri
            # LSP positions arrive as JSON numbers at this untyped request boundary.
            line: int = int(cast("int | float | str", optional[0]))
            character: int = int(cast("int | float | str", optional[1]))

            logger.info(f"Insert type request at {uri}:{line}:{character}")

            source: str = doc_context.source
            file_path: str = doc_context.file_path

            workflow = self.workflow

            # Per-request cancel token; a cancel sets its flag to stop the inference worker.
            cancel_token = CancellationToken()

            try:
                annotation_result = await workflow.annotate_at_position(
                    source=source,
                    file_path=file_path,
                    line=line,
                    character=character,
                    cancel_token=cancel_token,
                    uri=doc_context.uri,
                    version=doc_context.version,
                )
            except asyncio.CancelledError:
                cancel_token.cancel()
                logger.info("Type insertion cancelled by client")
                return {"success": False, "message": "Operation cancelled by user."}

            if not bool(annotation_result["insertion_success"]):
                message = str(annotation_result.get("error_message") or "")
                logger.warning(message)
                return {
                    "success": False,
                    "message": message or "Could not infer type at cursor position",
                }

            modified_source = str(annotation_result["modified_source"])
            workspace_edit = build_full_document_workspace_edit(
                uri, source, modified_source, doc_context.version
            )

            name = annotation_result.get("name") or "expression"
            total_time = (time.time() - request_start) * 1000
            logger.info(f"Successfully created edit for {name} in {total_time:.1f}ms")
            return {
                "success": True,
                "edits": workspace_edit,
                "message": annotation_result["message"],
            }

        except Exception as e:
            logger.error(f"Error in insert_type: {e}", exc_info=True)
            return {"success": False, "message": f"Internal error: {e!s}"}

    async def insert_types_in_file(self, ls: LanguageServer, params: list[Any]) -> dict[str, Any]:
        """Insert type annotations for all inferred types in a file."""
        try:
            doc_context, _ = extract_uri_and_context(ls, params)
            uri = doc_context.uri
            logger.info(f"Insert all types request for {uri}")

            source: str = doc_context.source
            file_path: str = doc_context.file_path

            workflow = self.workflow

            cancel_token = CancellationToken()

            try:
                modified_source: str
                inserted_count: int
                message: str
                # variable_drop_reasons is folded into insert_all_types' existing selection pass,
                # so there is no second mypy run and no post-insert await that could discard a
                # successful edit on a non-Cancelled raise.
                variable_drop_reasons: dict[str, int]
                (
                    modified_source,
                    inserted_count,
                    variable_drop_reasons,
                    message,
                ) = await workflow.insert_all_types(
                    source,
                    file_path,
                    cancel_token=cancel_token,
                    uri=doc_context.uri,
                    version=doc_context.version,
                )

                if inserted_count == 0:
                    logger.info(message)
                    return {
                        "success": False,
                        "message": message,
                        "inserted_count": 0,
                        "variable_drop_reasons": variable_drop_reasons,
                    }

                workspace_edit = build_full_document_workspace_edit(
                    uri, source, modified_source, doc_context.version
                )

                logger.info(message)
                return {
                    "success": True,
                    "edits": workspace_edit,
                    "inserted_count": inserted_count,
                    "message": message,
                    "variable_drop_reasons": variable_drop_reasons,
                }

            except asyncio.CancelledError:
                cancel_token.cancel()
                logger.info("Insert all types cancelled by client")
                return {
                    "success": False,
                    "message": "Operation cancelled by user.",
                    "inserted_count": 0,
                }

        except Exception as e:
            logger.error(f"Error in insert_types_in_file: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"Internal error: {e!s}",
                "inserted_count": 0,
            }

    async def remove_types_in_file(self, ls: LanguageServer, params: Any) -> dict[str, Any]:
        """Remove annotations (params [uri, vars|None=all, include_functions, line?]); -> dict."""
        try:
            doc_context, optional_params = extract_uri_and_context(ls, params, num_optional=3)
            uri = doc_context.uri
            # Optional args at this untyped LSP boundary: [variable names, include_functions, line].
            variables: list[str] | None = (
                cast("list[str]", optional_params[0]) if optional_params[0] is not None else None
            )
            include_functions: bool = (
                bool(optional_params[1]) if optional_params[1] is not None else False
            )
            # Wire line is 0-based (as in fangtype/insertType); LibCST positions are 1-based.
            # None scopes removal to the whole file, which is what the remove-all path sends.
            line: int | None = (
                int(cast("int", optional_params[2])) + 1 if optional_params[2] is not None else None
            )

            logger.info(
                f"Remove types request for {uri} "
                f"(variables={variables}, include_functions={include_functions}, line={line})"
            )

            source: str = doc_context.source

            # Use workflow for removal (sync - fast CPU-bound operation)
            workflow = self.workflow
            # remove_types returns dict[str, object]; rebind via an Any-typed local to read as Any.
            modified_source, result_info_obj = workflow.remove_types(
                source, variables, include_functions, line
            )
            result_info: dict[str, Any] = result_info_obj

            if not result_info["success"]:
                return {
                    "success": False,
                    "message": result_info["message"],
                    "removed_count": 0,
                    "not_found": result_info.get("not_found", []),
                    "skipped": result_info.get("will_skip", []),
                }

            workspace_edit = build_full_document_workspace_edit(
                uri, source, modified_source, doc_context.version
            )

            removed_count: int = result_info["removed_count"]
            not_found: list[str] = result_info.get("not_found", [])
            skipped: list[str] = result_info.get("will_skip", [])
            message: str = result_info["message"]

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

    def preview_removals(self, ls: LanguageServer, params: Any) -> dict[str, Any]:
        """Preview removals (sync; params [uri, vars|None=all, include_functions]); summary dict."""
        try:
            doc_context, optional_params = extract_uri_and_context(ls, params, num_optional=2)
            uri = doc_context.uri
            # Optional args at this untyped LSP boundary: [variable names, include_functions].
            variables: list[str] | None = (
                cast("list[str]", optional_params[0]) if optional_params[0] is not None else None
            )
            include_functions: bool = (
                bool(optional_params[1]) if optional_params[1] is not None else False
            )

            logger.info(
                f"Preview removals request for {uri} "
                f"(variables={variables}, include_functions={include_functions})"
            )

            source: str = doc_context.source

            # Get preview (sync - fast CPU-bound operation) via the workflow.
            workflow = self.workflow
            preview: dict[str, Any] = workflow.preview_removals(
                source, variables, include_functions
            )

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

    # ---- (5) Code actions --------------------------------------------------

    async def code_actions(self, params: types.CodeActionParams) -> list[types.CodeAction]:
        """Lightbulb: annotate unannotated variables."""
        # Per-request cancel token; a cancel sets its flag to stop the inference worker.
        cancel_token = CancellationToken()
        try:
            return await self.code_action_helper.get_insert_type_actions(
                self, params, cancel_token=cancel_token
            )
        except asyncio.CancelledError:
            cancel_token.cancel()
            logger.info("Code action inference cancelled by client")
            return []

    def on_shutdown(self, *_: object) -> None:
        """Release validator resources on shutdown; guarded so a failure never blocks it."""
        try:
            self.validator.close()
        except Exception:
            logger.debug("No validator resources to close on shutdown", exc_info=True)


def main() -> None:
    """Start the fangtype language server."""
    logger.info("Starting fangtype language server...")
    engine = resolve_engine_name(os.environ.get("FANGTYPE_ENGINE"))
    logger.info(f"Using inference engine: {engine}")
    server = FangtypeServer.from_container(build_container(engine))
    server.start_io()


if __name__ == "__main__":
    main()
