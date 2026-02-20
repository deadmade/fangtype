import { Uri, Position, Range, TextEdit, WorkspaceEdit } from 'vscode';
import type { LspTextEdit, LspWorkspaceEdit } from '../types';

/**
 * Convert LSP WorkspaceEdit JSON format to VSCode WorkspaceEdit object.
 *
 * The LSP server returns WorkspaceEdit as plain JSON which must be converted
 * to VSCode's WorkspaceEdit class before calling workspace.applyEdit().
 *
 * @param lspEdit - Plain object with LSP WorkspaceEdit structure
 * @returns VSCode WorkspaceEdit object
 */
export function lspWorkspaceEditToVscode(lspEdit: LspWorkspaceEdit): WorkspaceEdit {
    const vscodeEdit = new WorkspaceEdit();

    if (lspEdit.changes) {
        // Iterate over each file URI in the changes map
        for (const uriString in lspEdit.changes) {
            const textEdits = lspEdit.changes[uriString];
            const docUri = Uri.parse(uriString);

            if (!textEdits) {
                continue;
            }

            // Convert each LSP TextEdit to VSCode TextEdit
            const vscodeTextEdits = textEdits.map((lspTextEdit: LspTextEdit) => {
                const range = new Range(
                    new Position(lspTextEdit.range.start.line, lspTextEdit.range.start.character),
                    new Position(lspTextEdit.range.end.line, lspTextEdit.range.end.character)
                );
                return new TextEdit(range, lspTextEdit.newText);
            });

            // Set all edits for this document URI
            vscodeEdit.set(docUri, vscodeTextEdits);
        }
    }

    return vscodeEdit;
}
