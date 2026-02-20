import { workspace } from 'vscode';
import type { OutputChannel, WorkspaceEdit } from 'vscode';
import { LanguageClient } from 'vscode-languageclient/node';
import { retryOperation, isRetryableError, createRetryCallback } from '../retryUtils';

/**
 * Sends an LSP request with automatic retry logic for transient failures.
 *
 * @param client - Language client instance
 * @param outputChannel - Output channel for logging
 * @param statusBarItem - Status bar item for user feedback
 * @param method - LSP method name
 * @param params - Request parameters
 * @param operationName - Human-readable operation name for logging
 * @returns Promise resolving to the request result
 */
export async function sendLspRequestWithRetry<T>(
    client: LanguageClient,
    outputChannel: OutputChannel,
    method: string,
    params: unknown[],
    operationName: string
): Promise<T> {
    return retryOperation(() => client.sendRequest<T>(method, params), {
        maxRetries: 3,
        initialDelay: 200,
        shouldRetry: isRetryableError,
        onRetry: createRetryCallback(outputChannel, operationName, 3),
    });
}

/**
 * Applies a workspace edit with automatic retry logic for transient failures.
 *
 * @param edit - VSCode WorkspaceEdit to apply
 * @param outputChannel - Output channel for logging
 * @param statusBarItem - Status bar item for user feedback
 * @param operationName - Human-readable operation name for logging
 * @returns Promise resolving to success status
 */
export async function applyWorkspaceEditWithRetry(
    edit: WorkspaceEdit,
    outputChannel: OutputChannel,
    operationName: string
): Promise<boolean> {
    return retryOperation(() => Promise.resolve(workspace.applyEdit(edit)), {
        maxRetries: 3,
        initialDelay: 300,
        shouldRetry: isRetryableError,
        onRetry: createRetryCallback(outputChannel, operationName, 3),
    });
}
