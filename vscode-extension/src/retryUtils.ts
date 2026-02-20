import * as vscode from 'vscode';

/**
 * RETRY STRATEGY:
 *
 * The extension implements automatic retry for transient failures:
 * - LSP requests: 3 retries with exponential backoff (200ms -> 400ms -> 800ms)
 * - Server initialization: 3 retries with longer delays (1s -> 2s -> 4s)
 * - Workspace edits: 3 retries with medium delays (300ms -> 600ms -> 1200ms)
 * - Inlay hints: 1 retry with 300ms delay (performance-sensitive)
 *
 * Retryable errors:
 * - Network issues (ECONNREFUSED, ETIMEDOUT, ENOTFOUND)
 * - Server busy/unavailable (503)
 * - Timeouts
 * - File locks (transient)
 *
 * Non-retryable errors:
 * - Syntax errors
 * - Not found (404, file missing)
 * - Invalid parameters (400)
 * - User cancellation
 * - Binary not found (server init only)
 *
 * User feedback:
 * - Status bar shows retry attempts (e.g., "Inserting type (attempt 2/3)")
 * - Output channel logs all retry attempts for debugging
 * - Final error shown if all retries exhausted
 */

/**
 * Type for error objects that can be retryable
 */
export interface RetryableError {
    name?: string;
    message?: string;
    code?: string | number;
    errno?: string | number;
    statusCode?: number;
    status?: number;
    toString?: () => string;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    [key: string]: any;
}

/**
 * Options for retry operation
 */
export interface RetryOptions {
    /** Maximum number of retry attempts (default: 3) */
    maxRetries?: number;
    /** Initial delay in milliseconds (default: 200) */
    initialDelay?: number;
    /** Maximum delay between retries in milliseconds (default: 5000) */
    maxDelay?: number;
    /** Backoff multiplier for exponential backoff (default: 2) */
    backoffMultiplier?: number;
    /** Function to determine if an error should be retried */
    shouldRetry?: (error: RetryableError) => boolean;
    /** Callback invoked before each retry attempt */
    onRetry?: (attempt: number, error: RetryableError, nextDelay: number) => void;
}

/**
 * Sleep utility for delays between retry attempts
 */
function sleep(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Classifies errors to determine if they are retryable (transient) or permanent.
 *
 * Retryable errors include:
 * - Network errors (ECONNREFUSED, ETIMEDOUT, ENOTFOUND, ECONNRESET)
 * - Server busy/unavailable (503)
 * - Request timeouts
 * - File lock errors (EBUSY)
 *
 * Non-retryable errors include:
 * - Syntax errors
 * - Not found errors (404, ENOENT)
 * - Invalid parameters (400)
 * - Permission denied (403, EACCES)
 * - User cancellation
 *
 * @param error - The error to classify
 * @returns true if the error is likely transient and should be retried
 */
export function isRetryableError(error: RetryableError): boolean {
    if (!error) {
        return false;
    }

    // Check for user cancellation
    if (error.name === 'CancelledError' || error.message?.includes('cancel')) {
        return false;
    }

    // Check error code (for Node.js system errors)
    const errorCode = error.code || error.errno;
    if (errorCode) {
        const retryableCodes = [
            'ECONNREFUSED', // Connection refused
            'ETIMEDOUT', // Operation timed out
            'ENOTFOUND', // DNS lookup failed
            'ECONNRESET', // Connection reset by peer
            'EPIPE', // Broken pipe
            'EBUSY', // Resource busy (file lock)
            'EAGAIN', // Resource temporarily unavailable
            'EHOSTUNREACH', // Host unreachable
            'ENETUNREACH', // Network unreachable
            'EAI_AGAIN', // DNS temporary failure
        ];

        if (retryableCodes.includes(String(errorCode))) {
            return true;
        }

        // Non-retryable codes
        const nonRetryableCodes = [
            'ENOENT', // File not found
            'EACCES', // Permission denied
            'EPERM', // Operation not permitted
            'EEXIST', // File exists
            'EINVAL', // Invalid argument
        ];

        if (nonRetryableCodes.includes(String(errorCode))) {
            return false;
        }
    }

    // Check HTTP status codes
    const statusCode = error.statusCode || error.status || error.code;
    if (typeof statusCode === 'number') {
        // Retryable: 5xx server errors, 408 timeout, 429 too many requests
        if (statusCode === 408 || statusCode === 429 || (statusCode >= 500 && statusCode < 600)) {
            return true;
        }

        // Non-retryable: 4xx client errors (except 408, 429)
        if (statusCode >= 400 && statusCode < 500) {
            return false;
        }
    }

    // Check error message for common patterns
    const errorMessage = (error.message || error.toString?.() || String(error)).toLowerCase();

    // Retryable patterns
    const retryablePatterns = [
        'timeout',
        'timed out',
        'time out',
        'connection refused',
        'connection reset',
        'socket hang up',
        'network error',
        'econnrefused',
        'etimedout',
        'enotfound',
        'econnreset',
        'server unavailable',
        'service unavailable',
        'temporarily unavailable',
        'busy',
        'locked',
        'try again',
    ];

    if (retryablePatterns.some(pattern => errorMessage.includes(pattern))) {
        return true;
    }

    // Non-retryable patterns
    const nonRetryablePatterns = [
        'not found',
        'does not exist',
        'no such file',
        'syntax error',
        'parse error',
        'invalid',
        'permission denied',
        'access denied',
        'forbidden',
        'unauthorized',
        'bad request',
        'cancelled',
        'canceled',
    ];

    if (nonRetryablePatterns.some(pattern => errorMessage.includes(pattern))) {
        return false;
    }

    // Default: retry generic errors (conservative approach)
    // This covers unexpected errors that might be transient
    return true;
}

/**
 * Retries an async operation with exponential backoff.
 *
 * @param operation - The async operation to retry
 * @param options - Retry configuration options
 * @returns Promise resolving to the operation result
 * @throws The last error if all retry attempts are exhausted
 *
 * @example
 * ```typescript
 * const result = await retryOperation(
 *     () => client.sendRequest('method', params),
 *     {
 *         maxRetries: 3,
 *         initialDelay: 200,
 *         shouldRetry: isRetryableError,
 *         onRetry: (attempt, error, delay) => {
 *             console.log(`Retry attempt ${attempt}, waiting ${delay}ms`);
 *         }
 *     }
 * );
 * ```
 */
export async function retryOperation<T>(
    operation: () => Promise<T>,
    options: RetryOptions = {}
): Promise<T> {
    const {
        maxRetries = 3,
        initialDelay = 200,
        maxDelay = 5000,
        backoffMultiplier = 2,
        shouldRetry = isRetryableError,
        onRetry,
    } = options;

    let lastError: RetryableError | undefined;
    let currentDelay = initialDelay;

    for (let attempt = 0; attempt < maxRetries; attempt++) {
        try {
            return await operation();
        } catch (error) {
            const retryableError = error as RetryableError;
            lastError = retryableError;

            // Check if we should retry this error
            if (!shouldRetry(retryableError)) {
                throw error;
            }

            // If this was the last attempt, throw the error
            if (attempt === maxRetries - 1) {
                throw error;
            }

            // Calculate next delay with exponential backoff
            const nextDelay = Math.min(currentDelay, maxDelay);

            // Call retry callback if provided
            if (onRetry) {
                onRetry(attempt, retryableError, nextDelay);
            }

            // Wait before retrying
            await sleep(nextDelay);

            // Increase delay for next attempt
            currentDelay = currentDelay * backoffMultiplier;
        }
    }

    // This should never be reached, but TypeScript needs it
    throw lastError || new Error('Operation failed after retries');
}

/**
 * Logs a retry attempt with structured information.
 *
 * @param outputChannel - VSCode output channel for logging
 * @param operation - Name of the operation being retried
 * @param attempt - Current attempt number (0-based)
 * @param maxRetries - Maximum number of retries
 * @param error - The error that triggered the retry
 * @param nextDelay - Delay before next retry in milliseconds
 */
export function logRetryAttempt(
    outputChannel: vscode.OutputChannel,
    operation: string,
    attempt: number,
    maxRetries: number,
    error: RetryableError,
    nextDelay: number
): void {
    const timestamp = new Date().toISOString();
    const errorMessage = error?.message || error?.toString?.() || String(error ?? 'Unknown error');

    const message = [
        `[RETRY ${timestamp}]`,
        `Operation: ${operation}`,
        `Attempt: ${attempt + 1}/${maxRetries}`,
        `Error: ${errorMessage}`,
        `Next retry in: ${nextDelay}ms`,
    ].join(' | ');

    outputChannel.appendLine(message);
}
/**
 * Creates a retry callback that logs and shows status bar updates.
 *
 * @param outputChannel - VSCode output channel for logging
 * @param statusBar - VSCode status bar item for user feedback
 * @param operationName - Human-readable operation name
 * @param maxRetries - Maximum number of retries
 * @returns Retry callback function
 */
export function createRetryCallback(
    outputChannel: vscode.OutputChannel,
    operationName: string,
    maxRetries: number
): (attempt: number, error: RetryableError, nextDelay: number) => void {
    return (attempt: number, error: RetryableError, nextDelay: number) => {
        // Log structured retry information
        logRetryAttempt(outputChannel, operationName, attempt, maxRetries, error, nextDelay);
    };
}
