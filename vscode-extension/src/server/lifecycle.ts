import * as path from 'path';
import * as fs from 'fs';
import type { ExtensionContext, OutputChannel } from 'vscode';
import type { ServerOptions } from 'vscode-languageclient/node';
import { retryOperation, isRetryableError } from '../retryUtils';
import { LanguageClient } from 'vscode-languageclient/node';
import { window } from 'vscode';

/**
 * Get the path to the bundled LSP server binary.
 *
 * @param context - Extension context
 * @returns Path to bundled/tool/auto-type-server
 */
export function getBundledBinaryPath(context: ExtensionContext): string {
    return path.join(context.extensionPath, 'dist', 'auto-type-server');
}

/**
 * Get server options based on configuration and available server.
 * Performs diagnostic checks on the server binary before returning options.
 *
 * @param context - Extension context
 * @param outputChannel - Output channel for logging
 * @returns ServerOptions for the language client
 * @throws Error if binary is not found or not executable
 */
export async function getServerOptions(
    context: ExtensionContext,
    outputChannel: OutputChannel
): Promise<ServerOptions> {
    const binaryPath = getBundledBinaryPath(context);
    outputChannel.appendLine(`Extension path: ${context.extensionPath}`);
    outputChannel.appendLine(`Looking for server binary at: ${binaryPath}`);

    if (!fs.existsSync(binaryPath)) {
        const distPath = path.join(context.extensionPath, 'dist');
        const distExists = fs.existsSync(distPath);
        const distContents = distExists ? fs.readdirSync(distPath).join(', ') : '<missing>';
        throw new Error(
            `Bundled language server binary not found at ${binaryPath}. ` +
                `dist/ exists: ${distExists}, contents: [${distContents}]`
        );
    }

    // Log binary diagnostics for debugging CI issues
    const stats = fs.statSync(binaryPath);
    outputChannel.appendLine(
        `Server binary found: size=${stats.size} bytes, mode=${stats.mode.toString(8)}`
    );

    // Verify binary is executable
    try {
        fs.accessSync(binaryPath, fs.constants.X_OK);
        outputChannel.appendLine('Server binary is executable');
    } catch {
        outputChannel.appendLine('WARNING: Server binary is not executable, attempting chmod');
        fs.chmodSync(binaryPath, '755');
    }

    outputChannel.appendLine(`Using bundled binary: ${binaryPath}`);
    return {
        command: binaryPath,
        args: [],
    };
}

/**
 * Starts the language server with automatic retry logic.
 * Retries are useful for transient network or resource issues.
 *
 * @param client - Language client instance
 * @param outputChannel - Output channel for logging
 * @returns Promise that resolves when server starts successfully
 */
export async function startServerWithRetry(
    client: LanguageClient,
    outputChannel: OutputChannel
): Promise<void> {
    return retryOperation(() => client.start(), {
        maxRetries: 3,
        initialDelay: 1000, // Longer initial delay for server start
        maxDelay: 10000,
        shouldRetry: error => {
            // Don't retry if binary not found (permanent error)
            const errorMessage = error?.message || error?.toString() || '';
            if (
                errorMessage.includes('not found') ||
                errorMessage.includes('ENOENT') ||
                errorMessage.includes('does not exist')
            ) {
                return false;
            }
            return isRetryableError(error);
        },
        onRetry: (attempt, error, nextDelay) => {
            const errorMessage = error?.message || error?.toString() || 'Unknown error';
            outputChannel.appendLine(
                `[RETRY] Starting language server (attempt ${attempt + 2}/3): ${errorMessage} | Next retry in: ${nextDelay}ms`
            );
            window.showWarningMessage(`Retrying language server start (${attempt + 2}/3)...`);
        },
    });
}
