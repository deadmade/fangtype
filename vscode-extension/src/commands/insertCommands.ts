import { window } from 'vscode';
import type { TextEditor, OutputChannel } from 'vscode';
import { LanguageClient } from 'vscode-languageclient/node';
import type { AutoTypeResult, PreviewResult, PreviewItem } from '../types';
import { lspWorkspaceEditToVscode } from '../lsp/editUtils';
import { sendLspRequestWithRetry, applyWorkspaceEditWithRetry } from '../lsp/retryWrappers';

export async function insertTypeAtCursor(
    editor: TextEditor,
    client: LanguageClient,
    outputChannel: OutputChannel
): Promise<void> {
    try {
        const document = editor.document;
        const position = editor.selection.active;
        const uri = document.uri.toString();

        outputChannel.appendLine(
            `Insert type at cursor: ${uri}:${position.line}:${position.character}`
        );

        // Send request to server - let the server figure out the variable and type
        const result = await sendLspRequestWithRetry<AutoTypeResult>(
            client,
            outputChannel,
            'auto_type/insertType',
            [uri, position.line, position.character],
            'Insert type annotation'
        );

        outputChannel.appendLine(`Result: ${JSON.stringify(result)}`);

        if (result.success && result.edits) {
            // Convert LSP WorkspaceEdit JSON to VSCode format
            const vscodeEdit = lspWorkspaceEditToVscode(result.edits);
            outputChannel.appendLine(`Applying edit...`);
            const success = await applyWorkspaceEditWithRetry(
                vscodeEdit,
                outputChannel,
                'Apply type annotation'
            );

            if (success) {
                outputChannel.appendLine(`Edit applied successfully`);
                window.showInformationMessage(result.message || 'Type annotation inserted');
            } else {
                outputChannel.appendLine(`Edit application failed`);
                window.showErrorMessage('Failed to apply type annotation edit');
            }
        } else {
            outputChannel.appendLine(`Request failed: ${result.message}`);
            window.showErrorMessage(result.message || 'Failed to insert type annotation');
        }
    } catch (error) {
        outputChannel.appendLine(`Error: ${error}`);
        window.showErrorMessage(`Error inserting type: ${error}`);
    }
}

export async function insertAllTypesInFile(
    client: LanguageClient,
    outputChannel: OutputChannel,
    editor: TextEditor
): Promise<void> {
    try {
        const uri = editor.document.uri.toString();

        // Get preview first with retry logic
        const preview = await sendLspRequestWithRetry<PreviewResult>(
            client,
            outputChannel,
            'auto_type/previewInserts',
            [uri],
            'Preview type insertions'
        );

        if (!preview.success || preview.total_changes === 0) {
            window.showInformationMessage(preview.message || 'No types to insert in this file');
            return;
        }

        // Skip modal confirmation only in test mode (headless runs can't click dialogs).
        if (process.env.VSCODE_EXTENSION_TEST_MODE?.toString() !== 'true') {
            const accepted = await showPreviewMessage(preview);

            if (!accepted) return;
        }

        // Send request to insert all types with retry logic
        const result = await sendLspRequestWithRetry<AutoTypeResult>(
            client,
            outputChannel,
            'auto_type/insertTypesInFile',
            [uri],
            'Insert all type annotations'
        );

        if (result.success && result.edits) {
            // Convert LSP WorkspaceEdit JSON to VSCode format
            const vscodeEdit = lspWorkspaceEditToVscode(result.edits);
            const success = await applyWorkspaceEditWithRetry(
                vscodeEdit,
                outputChannel,
                'Apply type annotations'
            );

            if (success) {
                window.showInformationMessage(
                    result.message || `Inserted ${result.inserted_count} type annotations`
                );
            } else {
                window.showErrorMessage(
                    'Failed to apply type annotations. Check that the file is not read-only.'
                );
            }
        } else {
            window.showErrorMessage(result.message || 'Failed to insert types');
        }
    } catch (error) {
        window.showErrorMessage(`Error inserting types: ${error}`);
    }
}

async function showPreviewMessage(preview: PreviewResult): Promise<boolean> {
    // Show preview dialog
    const willInsert = preview.will_insert || [];
    const willSkip = preview.will_skip || [];

    const previewMessage = [
        `Will insert ${willInsert.length} type annotation(s):`,
        ...willInsert.slice(0, 10).map((item: PreviewItem) => `  • ${item.variable}: ${item.type}`),
        willInsert.length > 10 ? `  ... and ${willInsert.length - 10} more` : '',
        willSkip.length > 0 ? `\nWill skip ${willSkip.length} already-annotated variable(s)` : '',
    ]
        .filter(Boolean)
        .join('\n');

    const choice = await window.showInformationMessage(
        previewMessage,
        { modal: true },
        'Insert All'
    );

    if (choice !== 'Insert All') {
        return false;
    }

    return true;
}
