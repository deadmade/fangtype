import ast
import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING

from injector import inject
from lsprotocol import types
from pygls.lsp.server import LanguageServer

from fangtype.cancellation import CancellationToken
from fangtype.insertion import TargetType, build_source_index
from fangtype.utils.lsp_request_helper import (
    build_full_document_workspace_edit,
    get_document_context,
)
from fangtype.workflow import TypeAnnotationWorkflow

if TYPE_CHECKING:
    from fangtype.insertion import InsertionResult, InsertionTarget

logger = logging.getLogger(__name__)

# How much of a multi-target title may be spent naming what gets written, before the list is cut
# short. A menu entry the editor truncates itself tells the developer less than an ellipsis does.
_TITLE_TYPE_BUDGET = 80


def _requested_kinds_include_quickfix(only: Sequence[types.CodeActionKind | str]) -> bool:
    """Whether a client's ``context.only`` filter admits a QuickFix.

    LSP matches kinds by dotted prefix, so a request for ``quickfix`` admits ``quickfix.foo`` but
    a request for ``quickfix.foo`` does not admit the plain ``quickfix`` these actions carry. A
    client may send a kind the enum does not name, which arrives as a bare string.
    """
    offered = types.CodeActionKind.QuickFix.value
    for kind in only:
        # CodeActionKind subclasses str, so the enum check has to come first: an f-string of
        # a member renders 'CodeActionKind.QuickFix', not the wire value.
        requested = kind.value if isinstance(kind, types.CodeActionKind) else kind
        if not requested or requested == offered or offered.startswith(f"{requested}."):
            return True
    return False


def _enclosing_signature_line(source: str, line_0_based: int) -> int | None:
    """0-based ``def`` line of the signature that ``line_0_based`` continues, or None.

    A parameter written on a wrapped signature's continuation line carries the ``def`` line as its
    insertion line, so clicking the parameter itself finds nothing without this. Only a line
    strictly inside the signature resolves, since the ``def`` line has already been tried.
    """
    index = build_source_index(source)
    if index is None:
        return None

    clicked = line_0_based + 1
    innermost: int | None = None
    for node in ast.walk(index.tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not node.body:
            continue
        # The signature runs from `def` to the line before the body's first statement.
        if node.lineno < clicked < node.body[0].lineno and (
            innermost is None or node.lineno > innermost
        ):
            innermost = node.lineno
    return None if innermost is None else innermost - 1


def _describe(target: "InsertionTarget") -> str:
    """How one target reads in a multi-target title, as it will read in the source."""
    if target.target_type is TargetType.FUNCTION_RETURN:
        return f"-> {target.type_annotation}"
    return f"{target.name}: {target.type_annotation}"


def _action_title(targets: "list[InsertionTarget]") -> str:
    """Title for the single action that writes every annotation on the clicked line."""
    if len(targets) == 1:
        return f"Insert type annotation: {targets[0].type_annotation}"

    described = ", ".join(_describe(target) for target in targets)
    if len(described) > _TITLE_TYPE_BUDGET:
        described = described[:_TITLE_TYPE_BUDGET].rstrip(", ") + "…"
    return f"Insert {len(targets)} type annotations: {described}"


class CodeActionHelper:
    """Helper for code actions; validation/request-handling methods are async."""

    # @inject leaks Any via its overloads; no call-site annotation satisfies disallow_any_expr.
    @inject  # type: ignore[misc]
    def __init__(self, workflow: TypeAnnotationWorkflow) -> None:
        self.workflow = workflow

    async def get_insert_type_actions(
        self,
        ls: LanguageServer,
        params: types.CodeActionParams,
        cancel_token: CancellationToken | None = None,
    ) -> list[types.CodeAction]:
        """One 'Insert type annotation' action for everything insertable on the clicked line.

        The targets come from the same builder the file-wide insert uses, filtered to that line, so
        every kind the engine can write reaches the lightbulb rather than the simple assignments a
        regex could recognise. They are gated together and offered as a single action, so accepting
        annotates the whole line at once.
        """
        try:
            only = params.context.only
            if only is not None and not _requested_kinds_include_quickfix(only):
                return []

            uri: str = params.text_document.uri
            doc_context = get_document_context(ls, uri)
            source: str = doc_context.source

            targets = await self._targets_for_click(
                source,
                doc_context.file_path,
                params.range.start.line,
                doc_context.version,
                uri,
                cancel_token,
            )
            if not targets:
                return []

            # The assignability gate, the same one both insert requests end at. It drops the
            # targets when mypy rejects an annotation against its real right-hand side, which
            # leaves no action to offer.
            result: InsertionResult = await self.workflow.insert_with_assignability_gate(
                targets, source
            )

            if not result.success or result.inserted_count == 0:
                logger.debug(f"No action offered on line: {result.error_message}")
                return []

            workspace_edit = build_full_document_workspace_edit(
                uri, source, result.modified_source, doc_context.version
            )

            # Create code action with direct edit (not a command)
            action: types.CodeAction = types.CodeAction(
                title=_action_title(targets),
                kind=types.CodeActionKind.QuickFix,
                edit=workspace_edit,  # Direct edit, not a command
            )

            logger.debug(f"Offering code action for {len(targets)} target(s)")
            return [action]

        except Exception as e:
            logger.error(f"Error providing insert type actions: {e}", exc_info=True)
            return []

    async def _targets_for_click(
        self,
        source: str,
        file_path: str,
        start_line: int,
        version: int | None,
        uri: str,
        cancel_token: CancellationToken | None,
    ) -> "list[InsertionTarget]":
        """Targets on the clicked line, falling back to the signature the line continues."""
        targets = await self.workflow.prepare_targets_for_line(
            source, file_path, start_line, cancel_token=cancel_token, uri=uri, version=version
        )
        if targets:
            return targets

        signature_line = _enclosing_signature_line(source, start_line)
        if signature_line is None:
            return []
        # The second pass costs no inference: the first one cached it under (uri, version).
        return await self.workflow.prepare_targets_for_line(
            source, file_path, signature_line, cancel_token=cancel_token, uri=uri, version=version
        )
