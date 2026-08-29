import { CancellationTokenSource, workspace } from 'vscode';
import type { CancellationToken } from 'vscode';

/** Fallback timeout when `fangtype.requestTimeoutSeconds` is unset or invalid. */
export const DEFAULT_REQUEST_TIMEOUT_SECONDS = 120;

/**
 * Thrown when a write-path request doesn't resolve within its timeout. The message flows
 * through each call site's existing `catch` block, so a hang surfaces as a real error instead
 * of leaving a modal-confirmed action that never completes.
 */
export class RequestTimeoutError extends Error {
    constructor(label: string, timeoutMs: number) {
        super(`${label} timed out after ${Math.round(timeoutMs / 1000)}s`);
        this.name = 'RequestTimeoutError';
    }
}

/**
 * Resolve the request timeout from `fangtype.requestTimeoutSeconds` (default 120s).
 *
 * The server's own `_RUN_TIMEOUT_SECONDS` caps a single mypy run at 30s, but
 * `fangtype/insertTypesInFile` chains many bulk mypy probes in one request, so a flat 30s
 * client-side timeout would fire on a large file doing legitimate work.
 */
export function getRequestTimeoutMs(): number {
    const configured = workspace
        .getConfiguration('fangtype')
        .get<number>('requestTimeoutSeconds', DEFAULT_REQUEST_TIMEOUT_SECONDS);
    const seconds =
        typeof configured === 'number' && configured > 0
            ? configured
            : DEFAULT_REQUEST_TIMEOUT_SECONDS;
    return seconds * 1000;
}

/** The one `sendRequest` shape every call site needs; a real `LanguageClient` satisfies it. */
export interface RequestSender {
    sendRequest<T>(method: string, params: unknown, token?: CancellationToken): Promise<T>;
}

/**
 * Send one of the four write-path custom requests (`fangtype/insertType`,
 * `fangtype/insertTypesInFile`, `fangtype/removeTypesInFile`, `fangtype/previewRemovals`)
 * with a timeout, replacing what would otherwise be four inline `Promise.race` calls with
 * one helper.
 *
 * A real `CancellationToken` rides along on `sendRequest`, the same pattern `middleware.ts`
 * uses for stale-request cancellation. Where the server-side handler actually awaits (only
 * `insertType` and `insertTypesInFile` do), that lets a timeout cancel the server-side work
 * too. `removeTypesInFile` and `previewRemovals` run synchronously on the server and cannot
 * observe the cancellation, so a timeout there only stops the client from waiting on the
 * promise -- the server keeps running to completion regardless.
 */
export async function sendRequestWithTimeout<T>(
    client: RequestSender,
    method: string,
    params: unknown,
    label: string,
    timeoutMs: number = getRequestTimeoutMs()
): Promise<T> {
    const cts = new CancellationTokenSource();
    let timer: ReturnType<typeof setTimeout> | undefined;

    try {
        const requestPromise = client.sendRequest<T>(method, params, cts.token);
        // Where the timeout wins the race, this promise is still pending and may go on to
        // reject (e.g. the server observes the cancellation and rejects with a
        // CancellationError). Nothing else consumes it once it has lost, so give it a no-op
        // handler here -- it does not change what `Promise.race` below resolves or rejects
        // with, since that reads `requestPromise` itself, untouched.
        requestPromise.catch(() => {
            /* ignore: only the winner of the race below is observed */
        });

        return await Promise.race([
            requestPromise,
            new Promise<never>((_resolve, reject) => {
                timer = setTimeout(() => {
                    cts.cancel();
                    reject(new RequestTimeoutError(label, timeoutMs));
                }, timeoutMs);
            }),
        ]);
    } finally {
        if (timer !== undefined) {
            clearTimeout(timer);
        }
        cts.dispose();
    }
}
