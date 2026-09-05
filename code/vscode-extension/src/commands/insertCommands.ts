import { commands, window, workspace, Uri, EventEmitter } from 'vscode';
import type { TextEditor, OutputChannel, Disposable } from 'vscode';
import { LanguageClient } from 'vscode-languageclient/node';
import type { FangtypeResult } from '../types';
import {
    canApplyWholeFileReplace,
    lspWorkspaceEditToVscode,
    workspaceEditToPreviewText,
} from '../lsp/editUtils';
import { sendRequestWithTimeout } from '../lsp/requestTimeout';
import * as path from 'path';

/** Scheme for the insert-all diff's proposed side; an untitled doc would linger as a saveable tab. */
const PREVIEW_SCHEME = 'fangtype-preview';

// Keyed by preview URI (derived from the source path), so re-previewing a file replaces its entry.
// ponytail: never evicted; bounded by distinct files previewed per session, add onDidClose cleanup if that ever matters.
const previewContents = new Map<string, string>();
const previewChanged = new EventEmitter<Uri>();

/** Serve insert-all preview text as read-only virtual documents. Register once at activation. */
export function registerPreviewProvider(): Disposable {
    return workspace.registerTextDocumentContentProvider(PREVIEW_SCHEME, {
        onDidChange: previewChanged.event,
        provideTextDocumentContent: uri => previewContents.get(uri.toString()) ?? '',
    });
}

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
        const result = await sendRequestWithTimeout<FangtypeResult>(
            client,
            'fangtype/insertType',
            [uri, position.line, position.character],
            'Insert type annotation'
        );

        outputChannel.appendLine(`Result: ${JSON.stringify(result)}`);

        if (result.success && result.edits) {
            // Convert LSP WorkspaceEdit JSON to VSCode format
            const { edit: vscodeEdit, versions } = lspWorkspaceEditToVscode(result.edits);

            // Abort if the server never saw this buffer, or the buffer moved on.
            const expectedVersion = versions.get(uri);
            if (!canApplyWholeFileReplace(expectedVersion, document.version)) {
                if (expectedVersion === null) {
                    outputChannel.appendLine(
                        'Server returned version null for a whole-file replace; aborting'
                    );
                    window.showWarningMessage(
                        'Cannot apply a whole-file replace without a document version — please retry.'
                    );
                } else {
                    outputChannel.appendLine(
                        `Document changed (expected v${expectedVersion}, got v${document.version}); aborting`
                    );
                    window.showWarningMessage(
                        'Document changed since the type was computed — please retry.'
                    );
                }
                return;
            }

            outputChannel.appendLine(`Applying edit...`);
            const success = await workspace.applyEdit(vscodeEdit);

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

        const result = await sendRequestWithTimeout<FangtypeResult>(
            client,
            'fangtype/insertTypesInFile',
            [uri],
            'Insert all type annotations'
        );

        if (result.success && result.edits) {
            const previewText = workspaceEditToPreviewText(
                result.edits,
                uri,
                editor.document.getText()
            );

            // Keep the source path so the preview keeps the .py extension (syntax highlighting)
            // and two same-named files in different folders can't collide.
            const previewUri = Uri.from({ scheme: PREVIEW_SCHEME, path: editor.document.uri.path });
            previewContents.set(previewUri.toString(), previewText);
            previewChanged.fire(previewUri);

            const diffTitle = `Insert All Types Preview: ${path.basename(editor.document.fileName)}`;
            await commands.executeCommand(
                'vscode.diff',
                previewUri,
                editor.document.uri,
                diffTitle,
                { preview: true }
            );
        } else {
            window.showInformationMessage(result.message || 'No types to insert in this file');
        }
    } catch (error) {
        window.showErrorMessage(`Error inserting types: ${error}`);
    }
}
