import * as path from 'path';
import * as fs from 'fs';
import { workspace, ExtensionContext, commands, window, TextEditor, Position, Range, WorkspaceEdit, Uri, TextEdit, InlayHint } from 'vscode';
import {
    LanguageClient,
    LanguageClientOptions,
    ServerOptions,
    Middleware,
} from 'vscode-languageclient/node';
import { PythonExtension } from '@vscode/python-extension';

let client: LanguageClient;
let outputChannel: import('vscode').OutputChannel;

// Inlay hint cache: Map<documentUri, { version: number, hints: InlayHint[] }>
// Caches full-file hints to avoid redundant LSP requests on scroll events
const inlayHintCache = new Map<string, { version: number; hints: InlayHint[] }>();

/**
 * Middleware to cache inlay hints by document version.
 * The server returns hints for the entire file, so we can cache the full response
 * and filter client-side for the visible range.
 */
const middleware: Middleware = {
    provideInlayHints: async (document, range, token, next) => {
        const uri = document.uri.toString();
        const cached = inlayHintCache.get(uri);

        // Cache hit: same document version
        if (cached && cached.version === document.version) {
            // Filter cached hints to requested range
            return cached.hints.filter(hint =>
                hint.position.line >= range.start.line &&
                hint.position.line <= range.end.line
            );
        }

        // Cache miss: request full file range from server
        const fullRange = new Range(0, 0, document.lineCount, 0);
        const hints = await next(document, fullRange, token);

        if (hints && !token.isCancellationRequested) {
            // Cache the full response
            inlayHintCache.set(uri, {
                version: document.version,
                hints: hints as InlayHint[]
            });

            // Return only hints in requested range
            return (hints as InlayHint[]).filter(hint =>
                hint.position.line >= range.start.line &&
                hint.position.line <= range.end.line
            );
        }

        return hints;
    }
};

/**
 * Convert LSP WorkspaceEdit JSON format to VSCode WorkspaceEdit object.
 *
 * The LSP server returns WorkspaceEdit as plain JSON which must be converted
 * to VSCode's WorkspaceEdit class before calling workspace.applyEdit().
 *
 * @param lspEdit - Plain object with LSP WorkspaceEdit structure
 * @returns VSCode WorkspaceEdit object
 */
function lspWorkspaceEditToVscode(lspEdit: any): WorkspaceEdit {
    const vscodeEdit = new WorkspaceEdit();

    if (lspEdit.changes) {
        // Iterate over each file URI in the changes map
        for (const uriString in lspEdit.changes) {
            const textEdits = lspEdit.changes[uriString];
            const docUri = Uri.parse(uriString);

            // Convert each LSP TextEdit to VSCode TextEdit
            const vscodeTextEdits = textEdits.map((lspTextEdit: any) => {
                const range = new Range(
                    new Position(
                        lspTextEdit.range.start.line,
                        lspTextEdit.range.start.character
                    ),
                    new Position(
                        lspTextEdit.range.end.line,
                        lspTextEdit.range.end.character
                    )
                );
                return new TextEdit(range, lspTextEdit.newText);
            });

            // Set all edits for this document URI
            vscodeEdit.set(docUri, vscodeTextEdits);
        }
    }

    return vscodeEdit;
}

/**
 * Get the path to the bundled LSP server binary.
 *
 * @param context - Extension context
 * @returns Path to bundled/tool/auto-type-server (or .exe)
 */
function getBundledBinaryPath(context: ExtensionContext): string {
    const binaryName = process.platform === 'win32' ? 'auto-type-server.exe' : 'auto-type-server';
    return path.join(context.extensionPath, 'bundled', 'tool', binaryName);
}

/**
 * Get the path to the bundled LSP server script (fallback).
 *
 * @param context - Extension context
 * @returns Path to bundled/tool/lsp_server.py
 */
function getBundledScriptPath(context: ExtensionContext): string {
    return path.join(context.extensionPath, 'bundled', 'tool', 'lsp_server.py');
}

/**
 * Check if the bundled server exists.
 *
 * @param context - Extension context
 * @returns true if bundled server is available
 */
function hasBundledServer(context: ExtensionContext): boolean {
    // Check for binary first
    if (fs.existsSync(getBundledBinaryPath(context))) {
        return true;
    }
    // Check for script fallback
    const scriptPath = getBundledScriptPath(context);
    const autoTypePath = path.join(context.extensionPath, 'bundled', 'tool', 'auto_type');
    return fs.existsSync(scriptPath) && fs.existsSync(autoTypePath);
}

/**
 * Get the Python interpreter to use for running the bundled server.
 *
 * Priority:
 * 1. Custom interpreter from autoType.interpreter setting
 * 2. Active interpreter from ms-python.python extension
 * 3. 'python3' as fallback
 *
 * @returns Python interpreter command
 */
async function getPythonInterpreter(): Promise<string[]> {
    // Try to get interpreter from ms-python.python extension
    try {
        const pythonApi = await PythonExtension.api();
        await pythonApi.ready;

        // Get the active environment for the first workspace folder
        const workspaceFolder = workspace.workspaceFolders?.[0];
        if (workspaceFolder) {
            const environment = pythonApi.environments.getActiveEnvironmentPath(workspaceFolder.uri);
            if (environment) {
                const resolvedEnv = await pythonApi.environments.resolveEnvironment(environment);
                if (resolvedEnv?.executable?.uri) {
                    const pythonPath = resolvedEnv.executable.uri.fsPath;
                    outputChannel.appendLine(`Using Python from ms-python: ${pythonPath}`);
                    return [pythonPath];
                }
            }
        }

        // Fallback: try to get any known environment
        const knownEnvs = pythonApi.environments.known;
        if (knownEnvs.length > 0) {
            const firstEnv = await pythonApi.environments.resolveEnvironment(knownEnvs[0]);
            if (firstEnv?.executable?.uri) {
                const pythonPath = firstEnv.executable.uri.fsPath;
                outputChannel.appendLine(`Using first known Python environment: ${pythonPath}`);
                return [pythonPath];
            }
        }
    } catch (error) {
        outputChannel.appendLine(`Could not get Python from ms-python extension: ${error}`);
    }

    // Final fallback
    outputChannel.appendLine('Using fallback interpreter: python3');
    return ['python3'];
}

/**
 * Get server options based on configuration and available server.
 *
 * @param context - Extension context
 * @returns ServerOptions for the language client
 */
async function getServerOptions(context: ExtensionContext): Promise<ServerOptions> {
    // Priority 1: Bundled Binary
    const binaryPath = getBundledBinaryPath(context);
    if (fs.existsSync(binaryPath)) {
        outputChannel.appendLine(`Using bundled binary: ${binaryPath}`);
        return {
            command: binaryPath,
            args: [],
        };
    }

    // Priority 2: Bundled Script (if exists)
    const scriptPath = getBundledScriptPath(context);
    if (fs.existsSync(scriptPath)) {
        const pythonInterpreter = await getPythonInterpreter();
        outputChannel.appendLine(`Using bundled script: ${pythonInterpreter.join(' ')} ${scriptPath}`);
        return {
            command: pythonInterpreter[0],
            args: [...pythonInterpreter.slice(1), scriptPath],
        };
    }

    // Fallback: try bundled script path with python3
    outputChannel.appendLine('Falling back to bundled server with python3');
    return {
        command: 'python3',
        args: [getBundledScriptPath(context)],
    };
}

export async function activate(context: ExtensionContext) {
    // Create output channel for logging
    outputChannel = window.createOutputChannel('Auto Type Language Server');
    context.subscriptions.push(outputChannel);

    outputChannel.appendLine('Activating Auto Type extension...');

    // Get server options
    const serverOptions = await getServerOptions(context);

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
            fileEvents: workspace.createFileSystemWatcher('**/*.py')
        },
        initializationOptions: {
            validation: {
                enableMypyValidation: true
            }
        },
        middleware,
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
    client.start().then(() => {
        outputChannel.appendLine('Language server started successfully');

        // Command: Insert type at cursor
        const insertTypeCommand = commands.registerTextEditorCommand(
            'autoType.insertTypeAtCursor',
            async (editor: TextEditor) => {
                await insertTypeAtCursor(editor);
            }
        );

        // Command: Insert all types in file
        const insertAllTypesCommand = commands.registerCommand(
            'autoType.insertAllTypes',
            async () => {
                await insertAllTypesInFile();
            }
        );

        // Command: Remove type at cursor
        const removeTypeCommand = commands.registerTextEditorCommand(
            'autoType.removeTypeAtCursor',
            async (editor: TextEditor) => {
                await removeTypeAtCursor(editor);
            }
        );

        // Command: Remove all types in file
        const removeAllTypesCommand = commands.registerCommand(
            'autoType.removeAllTypes',
            async () => {
                await removeAllTypesInFile();
            }
        );

        // Clear inlay hint cache when documents are closed
        const cacheCleanup = workspace.onDidCloseTextDocument(doc => {
            inlayHintCache.delete(doc.uri.toString());
        });

        context.subscriptions.push(
            insertTypeCommand,
            insertAllTypesCommand,
            removeTypeCommand,
            removeAllTypesCommand,
            cacheCleanup
        );
    }).catch((error) => {
        outputChannel.appendLine(`Failed to start language server: ${error}`);
        window.showErrorMessage(`Auto Type: Failed to start language server. ${error}`);
    });
}

async function insertTypeAtCursor(editor: TextEditor): Promise<void> {
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

        // Request inlay hints to get the inferred type for this variable
        const hints = await commands.executeCommand<any[]>(
            'vscode.executeInlayHintProvider',
            uri,
            new Range(wordRange.start.line, 0, wordRange.start.line + 1, 0)
        );

        if (!hints || hints.length === 0) {
            window.showWarningMessage(`No type inferred for variable '${variableName}'`);
            return;
        }

        // Find the hint for this variable
        // Hints have format ": type" and are positioned after the variable name
        let inferredType: string | undefined;
        for (const hint of hints) {
            if (hint.position.line === wordRange.start.line) {
                // Extract type from label (remove ": " prefix)
                const label = typeof hint.label === 'string' ? hint.label : hint.label[0].value;
                inferredType = label.replace(/^:\s*/, '');
                break;
            }
        }

        if (!inferredType) {
            window.showWarningMessage(`No type inferred for variable '${variableName}'`);
            return;
        }

        // Send custom request to server to insert type
        const result = await client.sendRequest<any>(
            'auto_type/insertType',
            [uri, variableName, inferredType]
        );

        if (result.success && result.edits) {
            // Convert LSP WorkspaceEdit JSON to VSCode format
            const vscodeEdit = lspWorkspaceEditToVscode(result.edits);
            const success = await workspace.applyEdit(vscodeEdit);

            if (success) {
                window.showInformationMessage(`Inserted type annotation: ${variableName}: ${inferredType}`);
            } else {
                window.showErrorMessage('Failed to apply type annotation edit');
            }
        } else {
            window.showErrorMessage(result.message || 'Failed to insert type annotation');
        }

    } catch (error) {
        window.showErrorMessage(`Error inserting type: ${error}`);
    }
}

async function insertAllTypesInFile(): Promise<void> {
    try {
        const editor = window.activeTextEditor;
        if (!editor || editor.document.languageId !== 'python') {
            window.showWarningMessage('No active Python file');
            return;
        }

        const uri = editor.document.uri.toString();

        // Get preview first
        const preview = await client.sendRequest<any>(
            'auto_type/previewInserts',
            [uri]
        );

        if (!preview.success || preview.total_changes === 0) {
            window.showInformationMessage(
                preview.message || 'No types to insert in this file'
            );
            return;
        }

        // Show preview dialog
        const willInsert = preview.will_insert || [];
        const willSkip = preview.will_skip || [];

        const previewMessage = [
            `Will insert ${willInsert.length} type annotation(s):`,
            ...willInsert.slice(0, 10).map((item: any) => `  • ${item.variable}: ${item.type}`),
            willInsert.length > 10 ? `  ... and ${willInsert.length - 10} more` : '',
            willSkip.length > 0 ? `\nWill skip ${willSkip.length} already-annotated variable(s)` : ''
        ].filter(Boolean).join('\n');

        const choice = await window.showInformationMessage(
            previewMessage,
            { modal: true },
            'Insert All',
            'Cancel'
        );

        if (choice !== 'Insert All') {
            return;
        }

        // Send request to insert all types
        const result = await client.sendRequest<any>(
            'auto_type/insertTypesInFile',
            [uri]
        );

        if (result.success && result.edits) {
            // Convert LSP WorkspaceEdit JSON to VSCode format
            const vscodeEdit = lspWorkspaceEditToVscode(result.edits);
            const success = await workspace.applyEdit(vscodeEdit);

            if (success) {
                window.showInformationMessage(result.message || `Inserted ${result.inserted_count} type annotations`);
            } else {
                window.showErrorMessage('Failed to apply type annotations. Check that the file is not read-only.');
            }
        } else {
            window.showErrorMessage(result.message || 'Failed to insert types');
        }

    } catch (error) {
        window.showErrorMessage(`Error inserting types: ${error}`);
    }
}

async function removeTypeAtCursor(editor: TextEditor): Promise<void> {
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
            window.showWarningMessage(`Variable '${variableName}' has no type annotation to remove`);
            return;
        }

        // Send request to remove type for this specific variable
        const result = await client.sendRequest<any>(
            'auto_type/removeTypesInFile',
            [uri, [variableName], false]
        );

        if (result.success && result.edits) {
            const vscodeEdit = lspWorkspaceEditToVscode(result.edits);
            const success = await workspace.applyEdit(vscodeEdit);

            if (success) {
                window.showInformationMessage(`Removed type annotation from '${variableName}'`);
            } else {
                window.showErrorMessage('Failed to apply edit');
            }
        } else {
            window.showErrorMessage(result.message || `Could not remove type from '${variableName}'`);
        }

    } catch (error) {
        window.showErrorMessage(`Error removing type: ${error}`);
    }
}

async function removeAllTypesInFile(): Promise<void> {
    try {
        const editor = window.activeTextEditor;
        if (!editor || editor.document.languageId !== 'python') {
            window.showWarningMessage('No active Python file');
            return;
        }

        const uri = editor.document.uri.toString();

        // Get preview first
        const preview = await client.sendRequest<any>(
            'auto_type/previewRemovals',
            [uri, null]
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
            ...willRemove.slice(0, 10).map((item: any) =>
                `  • ${item.variable}: ${item.type} (line ${item.line})`
            ),
            willRemove.length > 10 ? `  ... and ${willRemove.length - 10} more` : '',
            willSkip.length > 0 ? `\nWill skip ${willSkip.length} variable(s) (no values)` : ''
        ].filter(Boolean).join('\n');

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
        const result = await client.sendRequest<any>(
            'auto_type/removeTypesInFile',
            [uri, null, false]
        );

        if (result.success && result.edits) {
            const vscodeEdit = lspWorkspaceEditToVscode(result.edits);
            const success = await workspace.applyEdit(vscodeEdit);

            if (success) {
                window.showInformationMessage(result.message || `Removed ${result.removed_count} type annotations`);
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

export function deactivate(): Thenable<void> | undefined {
    if (!client) {
        return undefined;
    }
    return client.stop();
}
