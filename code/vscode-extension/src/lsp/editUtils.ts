import { Uri, Position, Range, TextEdit, WorkspaceEdit } from 'vscode';
import type { LspTextEdit, LspWorkspaceEdit } from '../types';

function toVscodeTextEdits(textEdits: LspTextEdit[]): TextEdit[] {
    return textEdits.map((lspTextEdit: LspTextEdit) => {
        const range = new Range(
            new Position(lspTextEdit.range.start.line, lspTextEdit.range.start.character),
            new Position(lspTextEdit.range.end.line, lspTextEdit.range.end.character)
        );
        return new TextEdit(range, lspTextEdit.newText);
    });
}

/** Per-URI version an edit was computed against; null refuses a whole-file replace. */
type EditVersions = Map<string, number | null>;

/**
 * Whether a whole-file replacement may be applied to the live editor buffer.
 *
 * `null` means the server never opened this document (pygls reads from disk).
 * Applying that overwrite would discard unsaved edits. A number must match the
 * buffer version. `undefined` is the legacy unversioned `changes` form.
 */
export function canApplyWholeFileReplace(
    expectedVersion: number | null | undefined,
    documentVersion: number
): boolean {
    if (expectedVersion === null) {
        return false;
    }
    return expectedVersion === undefined || expectedVersion === documentVersion;
}

/**
 * Convert an LSP WorkspaceEdit (versioned `documentChanges`, else legacy `changes`) to VSCode form.
 *
 * @param lspEdit - Plain object with LSP WorkspaceEdit structure
 * @returns The VSCode WorkspaceEdit plus the versions to guard on before applying
 */
export function lspWorkspaceEditToVscode(lspEdit: LspWorkspaceEdit): {
    edit: WorkspaceEdit;
    versions: EditVersions;
} {
    const vscodeEdit = new WorkspaceEdit();
    const versions: EditVersions = new Map();

    if (lspEdit.documentChanges) {
        for (const change of lspEdit.documentChanges) {
            if (!change.edits) {
                continue;
            }
            const docUri = Uri.parse(change.textDocument.uri);
            vscodeEdit.set(docUri, toVscodeTextEdits(change.edits));
            versions.set(change.textDocument.uri, change.textDocument.version);
        }
    } else if (lspEdit.changes) {
        // Legacy unversioned form: no version to guard on.
        for (const uriString in lspEdit.changes) {
            const textEdits = lspEdit.changes[uriString];
            if (!textEdits) {
                continue;
            }
            vscodeEdit.set(Uri.parse(uriString), toVscodeTextEdits(textEdits));
        }
    }

    return { edit: vscodeEdit, versions };
}

/**
 * Validate the server's single full-document replacement edit and return its preview text.
 *
 * @param lspEdit - Plain object with LSP WorkspaceEdit structure
 * @param targetUri - URI of the document being previewed
 * @param currentText - Current document contents
 * @returns Proposed full document contents
 * @throws Error if the edit shape does not match the expected single-document replacement
 */
export function workspaceEditToPreviewText(
    lspEdit: LspWorkspaceEdit,
    targetUri: string,
    currentText: string
): string {
    let textEdits: LspTextEdit[] | undefined;

    if (lspEdit.documentChanges) {
        if (lspEdit.documentChanges.length !== 1) {
            throw new Error('Bulk insert preview only supports edits for the active document');
        }
        const change = lspEdit.documentChanges[0];
        if (!change || change.textDocument.uri !== targetUri) {
            throw new Error('Bulk insert preview only supports edits for the active document');
        }
        textEdits = change.edits;
    } else if (lspEdit.changes) {
        const uris = Object.keys(lspEdit.changes);
        if (uris.length !== 1 || uris[0] !== targetUri) {
            throw new Error('Bulk insert preview only supports edits for the active document');
        }
        textEdits = lspEdit.changes[targetUri];
    } else {
        throw new Error('Missing workspace edit changes');
    }

    const replacementEdit = textEdits && textEdits.length === 1 ? textEdits[0] : undefined;
    if (!replacementEdit) {
        throw new Error('Bulk insert preview expects a single full-document replacement edit');
    }

    const fullDocumentRange =
        replacementEdit.range.start.line === 0 &&
        replacementEdit.range.start.character === 0 &&
        replacementEdit.range.end.line >= currentText.split('\n').length - 1;

    if (!fullDocumentRange) {
        throw new Error('Bulk insert preview expects a full-document replacement edit');
    }

    return replacementEdit.newText;
}
