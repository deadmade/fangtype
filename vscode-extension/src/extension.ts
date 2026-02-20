import { workspace, commands, window } from 'vscode';
import type { ExtensionContext, OutputChannel, TextEditor } from 'vscode';
import { LanguageClient } from 'vscode-languageclient/node';
import type { LanguageClientOptions } from 'vscode-languageclient/node';

import { getServerOptions, startServerWithRetry } from './server/lifecycle';
import { createMiddleware, clearAllInlayHintCache, clearInlayHintCache } from './lsp/middleware';
import { insertTypeAtCursor, insertAllTypesInFile } from './commands/insertCommands';
import { removeTypeAtCursor, removeAllTypesInFile } from './commands/removeCommands';

let client: LanguageClient;
let outputChannel: OutputChannel;

/**
 * Get the language client instance.
 * Exposed for test access to check client state.
 */
export function getClient(): LanguageClient | undefined {
    return client;
}

/**
 * Extension API exposed via extension.exports for test access.
 */
export interface ExtensionApi {
    getClient: () => LanguageClient | undefined;
}

export async function activate(context: ExtensionContext): Promise<ExtensionApi> {
    // Create output channel for logging
    outputChannel = window.createOutputChannel('Auto Type Language Server');
    context.subscriptions.push(outputChannel);

    // Redirect output channel to console in test mode for visibility
    if (process.env.VSCODE_EXTENSION_TEST_MODE?.toString() === 'true') {
        activateConsoleOutput();
    }

    outputChannel.appendLine('Activating Auto Type extension... ');

    try {
        // Get server options
        const serverOptions = await getServerOptions(context, outputChannel);

        if ('command' in serverOptions) {
            outputChannel.appendLine(`Server command: ${serverOptions.command}`);
            if (serverOptions.args) {
                outputChannel.appendLine(`Server args: ${serverOptions.args.join(' ')}`);
            }
        }

        // Client options - configure the language client
        const clientOptions: LanguageClientOptions = {
            documentSelector: [{ scheme: 'file', language: 'python' }],
            synchronize: {
                fileEvents: workspace.createFileSystemWatcher('**/*.py'),
                configurationSection: 'autoType',
            },
            middleware: createMiddleware(outputChannel),
            outputChannel,
        };

        // Create the language client
        client = new LanguageClient(
            'autoType',
            'Auto Type Language Server',
            serverOptions,
            clientOptions
        );

        // Start the client and register commands when ready
        // Note: In vscode-languageclient v9+, start() returns a Promise
        try {
            await startServerWithRetry(client, outputChannel);
            outputChannel.appendLine('Language server started successfully');

            // Command: Insert type at cursor
            // Using registerCommand instead of registerTextEditorCommand for better
            // compatibility with programmatic execution via vscode.commands.executeCommand
            const insertTypeCommand = commands.registerCommand(
                'autoType.insertTypeAtCursor',
                async () => {
                    outputChannel.appendLine(`[COMMAND] insertTypeAtCursor invoked!`);
                    const editor = window.activeTextEditor;

                    if (!checkIfCommandShouldBeInvoked(editor)) return;

                    await insertTypeAtCursor(editor, client, outputChannel);
                    outputChannel.appendLine(`[COMMAND] insertTypeAtCursor completed`);
                }
            );

            // Command: Insert all types in file
            const insertAllTypesCommand = commands.registerCommand(
                'autoType.insertAllTypes',
                async () => {
                    const editor = window.activeTextEditor;
                    if (!checkIfCommandShouldBeInvoked(editor)) return;

                    await insertAllTypesInFile(client, outputChannel, editor);
                }
            );

            // Command: Remove type at cursor
            // Using registerCommand for better compatibility with programmatic execution
            const removeTypeCommand = commands.registerCommand(
                'autoType.removeTypeAtCursor',
                async () => {
                    const editor = window.activeTextEditor;
                    if (!checkIfCommandShouldBeInvoked(editor)) return;

                    await removeTypeAtCursor(editor, client, outputChannel);
                }
            );

            // Command: Remove all types in file
            const removeAllTypesCommand = commands.registerCommand(
                'autoType.removeAllTypes',
                async () => {
                    const editor = window.activeTextEditor;
                    if (!checkIfCommandShouldBeInvoked(editor)) return;

                    await removeAllTypesInFile(client, outputChannel);
                }
            );

            // Clear inlay hint cache when documents are closed
            const cacheCleanup = workspace.onDidCloseTextDocument(doc => {
                const uri = doc.uri.toString();
                clearInlayHintCache(uri);
            });

            const configChanged = workspace.onDidChangeConfiguration(async event => {
                if (!event.affectsConfiguration('autoType')) {
                    return;
                }

                outputChannel.appendLine(
                    '[CONFIG] autoType settings changed, clearing inlay hint caches'
                );
                clearAllInlayHintCache();

                // Best effort: force inlay hints refresh so users see changes immediately.
                try {
                    await commands.executeCommand('editor.action.inlayHints.refresh');
                } catch (error) {
                    outputChannel.appendLine(`[CONFIG] Inlay hints refresh failed: ${error}`);
                }
            });

            context.subscriptions.push(
                insertTypeCommand,
                insertAllTypesCommand,
                removeTypeCommand,
                removeAllTypesCommand,
                cacheCleanup,
                configChanged
            );
        } catch (error) {
            outputChannel.appendLine(`Failed to start language server after retries: ${error}`);
            window.showErrorMessage(
                `Auto Type: Failed to start language server after 3 attempts. ${error}`
            );
            throw error;
        }
    } catch (error) {
        outputChannel.appendLine(`Failed to initialize server options: ${error}`);
        window.showErrorMessage(`Auto Type: Failed to initialize language server. ${error}`);
        throw error;
    }

    return { getClient };
}

export function deactivate(): Thenable<void> | undefined {
    if (!client) {
        return undefined;
    }
    return client.stop();
}

function activateConsoleOutput() {
    const originalAppendLine = outputChannel.appendLine.bind(outputChannel);
    const originalAppend = outputChannel.append.bind(outputChannel);

    outputChannel.appendLine = (value: string) => {
        console.log(`[Auto Type] ${value}`);
        originalAppendLine(value);
    };

    outputChannel.append = (value: string) => {
        console.log(`[Auto Type] ${value}`);
        originalAppend(value);
    };
}

function checkIfCommandShouldBeInvoked(editor: TextEditor | undefined): editor is TextEditor {
    if (!editor) {
        window.showWarningMessage('No active text editor');
        return false;
    }
    if (editor.document.languageId !== 'python') {
        window.showWarningMessage('Active file is not a Python file');
        return false;
    }

    return true;
}
