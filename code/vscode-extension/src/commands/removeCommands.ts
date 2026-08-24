import { window, workspace } from 'vscode';
import type { TextEditor } from 'vscode';
import { LanguageClient } from 'vscode-languageclient/node';
import type { FangtypeResult, PreviewResult, PreviewItem } from '../types';
import { canApplyWholeFileReplace, lspWorkspaceEditToVscode } from '../lsp/editUtils';
import { sendRequestWithTimeout } from '../lsp/requestTimeout';

export async function removeTypeAtCursor(
    editor: TextEditor,
    client: LanguageClient
): Promise<void> {
    try {
        const document = editor.document;
        const position = editor.selection.active;
        const uri = document.uri.toString();

        // Get the word at cursor position (variable name)
        const wordRange = document.getWordRangeAtPosition(position);
        if (!wordRange) {
            window.showWarningMessage('No variable found at cursor position');
            return;
        }

        const variableName = document.getText(wordRange);

        // Cheap annotation check: does the line carry a ':' at all? Requiring '=' too would
        // refuse a standalone `total: int`, which is exactly the shape the insert path writes
        // for a binding PEP 526 cannot annotate in place. The server decides what is actually
        // removable and reports what it skipped.
        const line = document.lineAt(wordRange.start.line);
        const lineText = line.text;

        if (!lineText.includes(':')) {
            window.showWarningMessage(
                `Variable '${variableName}' has no type annotation to remove`
            );
            return;
        }

        // Scope the removal to the cursor's line; a bare name would match every scope in the file.
        const result = await sendRequestWithTimeout<FangtypeResult>(
            client,
            'fangtype/removeTypesInFile',
            [uri, [variableName], true, wordRange.start.line],
            'Remove type annotation'
        );

        if (result.success && result.edits) {
            const { edit: vscodeEdit, versions } = lspWorkspaceEditToVscode(result.edits);

            const expectedVersion = versions.get(uri);
            if (!canApplyWholeFileReplace(expectedVersion, document.version)) {
                window.showWarningMessage(
                    expectedVersion === null
                        ? 'Cannot apply a whole-file replace without a document version — please retry.'
                        : 'Document changed since the removal was computed — please retry.'
                );
                return;
            }

            const success = await workspace.applyEdit(vscodeEdit);

            if (success) {
                window.showInformationMessage(`Removed type annotation from '${variableName}'`);
            } else {
                window.showErrorMessage('Failed to apply edit');
            }
        } else {
            window.showErrorMessage(
                result.message || `Could not remove type from '${variableName}'`
            );
        }
    } catch (error) {
        window.showErrorMessage(`Error removing type: ${error}`);
    }
}

export async function removeAllTypesInFile(client: LanguageClient): Promise<void> {
    try {
        const editor = window.activeTextEditor;
        if (!editor || editor.document.languageId !== 'python') {
            window.showWarningMessage('No active Python file');
            return;
        }

        const uri = editor.document.uri.toString();

        // Get preview first
        const preview = await sendRequestWithTimeout<PreviewResult>(
            client,
            'fangtype/previewRemovals',
            [uri, null, true],
            'Preview type removal'
        );

        if (!preview.success || preview.total_changes === 0) {
            window.showInformationMessage(
                preview.message || 'No type annotations to remove in this file'
            );
            return;
        }

        // Show preview dialog
        const willRemove = preview.will_remove || [];
        const willSkip = preview.will_skip || [];

        const previewMessage = [
            `Will remove ${willRemove.length} type annotation(s):`,
            ...willRemove
                .slice(0, 10)
                .map(
                    (item: PreviewItem) => `  • ${item.variable}: ${item.type} (line ${item.line})`
                ),
            willRemove.length > 10 ? `  ... and ${willRemove.length - 10} more` : '',
            willSkip.length > 0 ? `\nWill skip ${willSkip.length} variable(s) (no values)` : '',
        ]
            .filter(Boolean)
            .join('\n');

        const choice = await window.showWarningMessage(
            previewMessage,
            { modal: true },
            'Remove All',
            'Cancel'
        );

        if (choice !== 'Remove All') {
            return;
        }

        // Send request to remove all types
        const result = await sendRequestWithTimeout<FangtypeResult>(
            client,
            'fangtype/removeTypesInFile',
            [uri, null, true],
            'Remove all type annotations'
        );

        if (result.success && result.edits) {
            const { edit: vscodeEdit, versions } = lspWorkspaceEditToVscode(result.edits);

            const expectedVersion = versions.get(uri);
            if (!canApplyWholeFileReplace(expectedVersion, editor.document.version)) {
                window.showWarningMessage(
                    expectedVersion === null
                        ? 'Cannot apply a whole-file replace without a document version — please retry.'
                        : 'Document changed since the removal was computed — please retry.'
                );
                return;
            }

            const success = await workspace.applyEdit(vscodeEdit);

            if (success) {
                window.showInformationMessage(
                    result.message || `Removed ${result.removed_count} type annotations`
                );
            } else {
                window.showErrorMessage('Failed to apply changes');
            }
        } else {
            window.showErrorMessage(result.message || 'Failed to remove types');
        }
    } catch (error) {
        window.showErrorMessage(`Error removing types: ${error}`);
    }
}
