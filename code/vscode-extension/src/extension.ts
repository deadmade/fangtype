import { commands, window, workspace } from 'vscode';
import type { ExtensionContext, LogOutputChannel, TextEditor } from 'vscode';
import { DidChangeConfigurationNotification, LanguageClient } from 'vscode-languageclient/node';

import { SERVER_ID, SERVER_NAME } from './common/constants';
import { registerLogger, traceLog } from './common/log/logging';
import { initializePython, onDidChangePythonInterpreter } from './common/python';
import {
    checkIfConfigurationChanged,
    checkIfInfraConfigurationChanged,
    getExtensionSettings,
    getGlobalSettings,
    getWorkspaceSettings,
} from './common/settings';
import type { ISettings } from './common/settings';
import {
    createSerialRunner,
    logLevelToTrace,
    resolveInterpreter,
    restartServer,
} from './common/server';
import { removeVenv } from './common/venv';
import { traceError } from './common/log/logging';
import { clearInlayHintCache } from './lsp/middleware';
import {
    insertTypeAtCursor,
    insertAllTypesInFile,
    registerPreviewProvider,
} from './commands/insertCommands';
import { removeTypeAtCursor, removeAllTypesInFile } from './commands/removeCommands';

let lsClient: LanguageClient | undefined;
let outputChannel: LogOutputChannel;

/** Get the language client instance; exposed so tests can check client state. */
export function getClient(): LanguageClient | undefined {
    return lsClient;
}

/** Extension API exposed via extension.exports for test access. */
export interface ExtensionApi {
    getClient: () => LanguageClient | undefined;
}

/** Launch settings: the first workspace folder's, else the folder-independent global settings. */
function launchSettings(): ISettings {
    const folder = workspace.workspaceFolders?.[0];
    return folder ? getWorkspaceSettings(SERVER_ID, folder) : getGlobalSettings(SERVER_ID);
}

export async function activate(context: ExtensionContext): Promise<ExtensionApi> {
    // Leveled log channel + module-level trace helpers.
    outputChannel = window.createOutputChannel(SERVER_NAME, { log: true });
    context.subscriptions.push(outputChannel, registerLogger(outputChannel));

    // Mirror channel output to the console in test mode for visibility.
    if (process.env.VSCODE_EXTENSION_TEST_MODE?.toString() === 'true') {
        activateConsoleOutput(outputChannel);
    }

    traceLog(`Activating ${SERVER_NAME} extension...`);

    // Resolve the interpreter via the Python extension (no-op when it is absent).
    await initializePython(context.subscriptions);

    // Where the managed venv lives (the extension install dir is read-only in production).
    const globalStoragePath = context.globalStorageUri.fsPath;

    // (Re)launch the server under the currently-resolved interpreter/settings. Serialized: two
    // overlapping callers (e.g. interpreter-change + restart command) must not both read/restart
    // `lsClient` concurrently and orphan a client (M10).
    const runServer = createSerialRunner(async (): Promise<void> => {
        lsClient = await restartServer(
            launchSettings(),
            outputChannel,
            globalStoragePath,
            lsClient
        );
    });

    // Restart when the user selects a different interpreter.
    context.subscriptions.push(
        onDidChangePythonInterpreter(() => {
            void runServer();
        })
    );

    // Push settings to the server on change (replaces the config-pull sync).
    context.subscriptions.push(
        workspace.onDidChangeConfiguration(async event => {
            if (!checkIfConfigurationChanged(event, SERVER_ID)) {
                return;
            }
            if (checkIfInfraConfigurationChanged(event, SERVER_ID)) {
                traceLog('Fangtype infra settings changed; relaunching server.');
                await runServer();
                return;
            }
            traceLog('Fangtype settings changed; pushing to server.');
            // Folderless window has no per-folder settings; send globals instead.
            // `globalSettings` is not part of DidChangeConfigurationParams and the server's
            // did_change_configuration handler only reads `settings` (globalSettings is
            // handshake-only, via initializationOptions) — don't send a property it can't use.
            const folderSettings = getExtensionSettings(SERVER_ID);
            await lsClient?.sendNotification(DidChangeConfigurationNotification.type, {
                settings:
                    folderSettings.length > 0 ? folderSettings : [getGlobalSettings(SERVER_ID)],
            });
            // logLevel also drives JSON-RPC tracing (merged fangtype.trace.server); apply live.
            await lsClient?.setTrace(logLevelToTrace(launchSettings().logLevel));
        })
    );

    // Clear per-document inlay hint cache on close.
    context.subscriptions.push(
        workspace.onDidCloseTextDocument(doc => clearInlayHintCache(doc.uri.toString()))
    );

    context.subscriptions.push(registerPreviewProvider());

    // Register ONCE at activation, not on start-success, so a restart can't double-register.
    context.subscriptions.push(
        commands.registerCommand('fangtype.insertTypeAtCursor', async () => {
            if (!lsClient) return;
            const editor = window.activeTextEditor;
            if (!checkIfCommandShouldBeInvoked(editor)) return;
            await insertTypeAtCursor(editor, lsClient, outputChannel);
        }),
        commands.registerCommand('fangtype.insertAllTypes', async () => {
            if (!lsClient) return;
            const editor = window.activeTextEditor;
            if (!checkIfCommandShouldBeInvoked(editor)) return;
            await insertAllTypesInFile(lsClient, outputChannel, editor);
        }),
        commands.registerCommand('fangtype.removeTypeAtCursor', async () => {
            if (!lsClient) return;
            const editor = window.activeTextEditor;
            if (!checkIfCommandShouldBeInvoked(editor)) return;
            await removeTypeAtCursor(editor, lsClient);
        }),
        commands.registerCommand('fangtype.removeAllTypes', async () => {
            if (!lsClient) return;
            const editor = window.activeTextEditor;
            if (!checkIfCommandShouldBeInvoked(editor)) return;
            await removeAllTypesInFile(lsClient);
        }),
        commands.registerCommand('fangtype.restart', async () => {
            await runServer();
        }),
        commands.registerCommand('fangtype.rebuildEnvironment', async () => {
            // Delete the managed venv; the relaunch below rebuilds it (corruption, dep bump).
            try {
                const base = await resolveInterpreter(launchSettings());
                await removeVenv(globalStoragePath, base);
            } catch (error) {
                traceError(`Fangtype: failed to remove the managed environment: ${error}`);
            }
            await runServer();
        })
    );

    await runServer();

    return { getClient };
}

export function deactivate(): Thenable<void> | undefined {
    return lsClient?.stop();
}

function activateConsoleOutput(channel: LogOutputChannel): void {
    const originalAppendLine = channel.appendLine.bind(channel);
    const originalAppend = channel.append.bind(channel);

    channel.appendLine = (value: string) => {
        console.log(`[Fangtype] ${value}`);
        originalAppendLine(value);
    };

    channel.append = (value: string) => {
        console.log(`[Fangtype] ${value}`);
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
