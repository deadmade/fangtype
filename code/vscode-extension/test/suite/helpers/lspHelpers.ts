import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';

/** Sleep utility. */
export function sleep(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms));
}

/** Get extension instance. */
export function getExtension(): vscode.Extension<unknown> | undefined {
    return vscode.extensions.getExtension('fangtype.fangtype');
}

/** Server runs from source: `bundled/tool/lsp_server.py` must exist, not a binary. */
export function verifyBundledServerExists(): boolean {
    const extension = getExtension();
    if (!extension) {
        throw new Error('Extension not found');
    }

    const serverScript = path.join(extension.extensionPath, 'bundled', 'tool', 'lsp_server.py');

    if (!fs.existsSync(serverScript)) {
        throw new Error(`Server bootstrap not found at: ${serverScript}`);
    }

    return true;
}

/** Check if all required commands are registered. */
export async function areCommandsRegistered(): Promise<boolean> {
    const commands = await vscode.commands.getCommands();
    const requiredCommands = [
        'fangtype.insertTypeAtCursor',
        'fangtype.insertAllTypes',
        'fangtype.removeTypeAtCursor',
        'fangtype.removeAllTypes',
    ];

    return requiredCommands.every(cmd => commands.includes(cmd));
}

/** Trigger extension activation by opening a Python file. */
export async function triggerExtensionActivation(): Promise<vscode.TextEditor> {
    // Check if extension is already active
    const extension = getExtension();
    if (extension?.isActive) {
        console.log('Extension already active');
    }

    // Open Python file to trigger activation
    const doc = await vscode.workspace.openTextDocument({
        language: 'python',
        content: 'trigger_activation_var = 1\n',
    });

    const editor = await vscode.window.showTextDocument(doc);
    console.log('Opened Python file to trigger extension activation');

    return editor;
}

/** Check if LSP server is responding to requests. */
export async function isLspServerRunning(): Promise<boolean> {
    const editor = vscode.window.activeTextEditor;
    if (!editor || editor.document.languageId !== 'python') {
        return false;
    }

    try {
        const hints = await vscode.commands.executeCommand<vscode.InlayHint[]>(
            'vscode.executeInlayHintProvider',
            editor.document.uri,
            new vscode.Range(0, 0, Math.min(5, editor.document.lineCount), 0)
        );

        return hints !== undefined;
    } catch {
        return false;
    }
}

/** Get LSP server logs from output channel. */
export async function getLspServerLogs(): Promise<string> {
    // Try to find Fangtype output channel
    const channels = await vscode.commands.executeCommand<string[]>(
        'workbench.action.output.show.extension-output'
    );

    // Look for output channel with our extension name
    const fangtypeChannel = channels?.find(
        ch => ch.toLowerCase().includes('auto') || ch.toLowerCase().includes('type')
    );

    if (fangtypeChannel) {
        await vscode.commands.executeCommand('workbench.action.output.show', fangtypeChannel);
        // Give it a moment to populate
        await sleep(100);
    }

    return '';
}

/** Get server information. */
export function getServerInfo(): { version?: string; status?: string } {
    const extension = getExtension();

    return {
        status: extension?.isActive ? 'active' : 'inactive',
    };
}

/** Get extension output channel. */
export async function getExtensionOutputChannel(): Promise<vscode.OutputChannel | undefined> {
    const extension = getExtension();
    if (!extension?.isActive) {
        return undefined;
    }

    // The activation-created channel is internal and not exported, so nothing to hand back.
    return undefined;
}
