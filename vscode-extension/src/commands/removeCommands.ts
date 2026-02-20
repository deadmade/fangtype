import { window } from 'vscode';
import type { TextEditor, OutputChannel } from 'vscode';
import { LanguageClient } from 'vscode-languageclient/node';
import type { AutoTypeResult, PreviewResult, PreviewItem } from '../types';
import { lspWorkspaceEditToVscode } from '../lsp/editUtils';
import { sendLspRequestWithRetry, applyWorkspaceEditWithRetry } from '../lsp/retryWrappers';

export async function removeTypeAtCursor(
    editor: TextEditor,
    client: LanguageClient,
    outputChannel: OutputChannel
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

        // Check if this variable has a type annotation
        // Simple check: does the line contain ": " before "="?
        const line = document.lineAt(wordRange.start.line);
        const lineText = line.text;

        if (!lineText.includes(':') || !lineText.includes('=')) {
            window.showWarningMessage(
                `Variable '${variableName}' has no type annotation to remove`
            );
            return;
        }

        // Send request to remove type for this specific variable with retry logic
        const result = await sendLspRequestWithRetry<AutoTypeResult>(
            client,
            outputChannel,
            'auto_type/removeTypesInFile',
            [uri, [variableName], false],
            'Remove type annotation'
        );

        if (result.success && result.edits) {
            const vscodeEdit = lspWorkspaceEditToVscode(result.edits);
            const success = await applyWorkspaceEditWithRetry(
                vscodeEdit,
                outputChannel,
                'Apply type removal'
            );

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

export async function removeAllTypesInFile(
    client: LanguageClient,
    outputChannel: OutputChannel
): Promise<void> {
    try {
        const editor = window.activeTextEditor;
        if (!editor || editor.document.languageId !== 'python') {
            window.showWarningMessage('No active Python file');
            return;
        }

        const uri = editor.document.uri.toString();

        // Get preview first with retry logic
        const preview = await sendLspRequestWithRetry<PreviewResult>(
            client,
            outputChannel,
            'auto_type/previewRemovals',
            [uri, null],
            'Preview type removals'
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

        // Send request to remove all types with retry logic
        const result = await sendLspRequestWithRetry<AutoTypeResult>(
            client,
            outputChannel,
            'auto_type/removeTypesInFile',
            [uri, null, false],
            'Remove all type annotations'
        );

        if (result.success && result.edits) {
            const vscodeEdit = lspWorkspaceEditToVscode(result.edits);
            const success = await applyWorkspaceEditWithRetry(
                vscodeEdit,
                outputChannel,
                'Apply type removals'
            );

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
