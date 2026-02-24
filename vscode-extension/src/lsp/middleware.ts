import { Range, CancellationTokenSource, InlayHint } from 'vscode';
import type { Middleware } from 'vscode-languageclient/node';
import { retryOperation, isRetryableError } from '../retryUtils';

// Inlay hint cache: Map<documentUri, { version: number, hints: InlayHint[] }>
// Caches full-file hints to avoid redundant LSP requests on scroll events
const inlayHintCache = new Map<string, { version: number; hints: InlayHint[] }>();

// Map to track in-flight requests to deduplicate concurrent calls for the same version
// We store the promise and a CancellationTokenSource to allow manual cancellation if needed
const inFlightRequests = new Map<
    string,
    { promise: Promise<InlayHint[] | null | undefined>; cts: CancellationTokenSource }
>();

// Track the latest version we've seen for each URI to cancel stale requests
const latestVersions = new Map<string, number>();

/**
 * Clear the inlay hint cache for a specific URI.
 * Called when a document is closed.
 *
 * @param uri - Document URI to clear cache for
 */
export function clearInlayHintCache(uri: string): void {
    inlayHintCache.delete(uri);
    latestVersions.delete(uri);

    // Cancel any in-flight requests for this URI
    for (const [key, entry] of inFlightRequests.entries()) {
        if (key.startsWith(`${uri}#`)) {
            entry.cts.cancel();
            entry.cts.dispose();
            inFlightRequests.delete(key);
        }
    }
}

/**
 * Clear all cached and in-flight inlay hint state.
 * Useful when settings changes should invalidate all previously computed hints.
 */
export function clearAllInlayHintCache(): void {
    inlayHintCache.clear();
    latestVersions.clear();

    for (const [, entry] of inFlightRequests.entries()) {
        entry.cts.cancel();
        entry.cts.dispose();
    }
    inFlightRequests.clear();
}

/**
 * Middleware to cache inlay hints by document version.
 * The server returns hints for the entire file, so we can cache the full response
 * and filter client-side for the visible range.
 */
export function createMiddleware(outputChannel: { appendLine: (msg: string) => void }): Middleware {
    return {
        provideInlayHints: async (document, range, token, next) => {
            const uri = document.uri.toString();
            const currentVersion = document.version;
            const versionedUri = `${uri}#${currentVersion}`;

            // 1. Check completed cache
            const cached = inlayHintCache.get(uri);
            if (cached && cached.version === currentVersion) {
                // Filter cached hints to requested range
                return cached.hints.filter(
                    hint =>
                        hint.position.line >= range.start.line &&
                        hint.position.line <= range.end.line
                );
            }

            // 2. Manage version tracking and stale request cancellation
            const lastVersion = latestVersions.get(uri) || 0;
            if (currentVersion > lastVersion) {
                // New version! Cancel in-flight request for the previous version
                const staleVersionedUri = `${uri}#${lastVersion}`;
                const staleEntry = inFlightRequests.get(staleVersionedUri);
                if (staleEntry) {
                    staleEntry.cts.cancel();
                    // We don't delete it here, it will delete itself in its finally block
                }
                latestVersions.set(uri, currentVersion);
            }

            // 3. Check in-flight requests to deduplicate
            let entry = inFlightRequests.get(versionedUri);
            if (!entry) {
                // Cache miss: request full file range from server
                const fullRange = new Range(0, 0, document.lineCount, 0);

                // Use a separate CancellationTokenSource for the server request.
                // This prevents the server request from being canceled just because
                // VS Code canceled the FIRST client-side call (e.g. during a refresh).
                const cts = new CancellationTokenSource();
                const result = next(document, fullRange, cts.token);

                // Ensure we have a Promise and filter out void
                const promise = Promise.resolve(result).then(
                    hints => hints ?? undefined
                ) as Promise<InlayHint[] | null | undefined>;

                entry = { promise, cts };
                inFlightRequests.set(versionedUri, entry);

                // Populate cache when finished
                promise
                    .then(hints => {
                        if (hints) {
                            inlayHintCache.set(uri, {
                                version: currentVersion,
                                hints: hints as InlayHint[],
                            });
                        }
                    })
                    .catch(() => {
                        /* ignore */
                    })
                    .finally(() => {
                        // Dispose the CancellationTokenSource to prevent memory leak
                        cts.dispose();
                        // Remove from in-flight map only if it's still the same entry
                        if (inFlightRequests.get(versionedUri) === entry) {
                            inFlightRequests.delete(versionedUri);
                        }
                    });
            }

            // At this point entry is guaranteed to be defined (assigned in the if block above)
            const requestEntry = entry;

            try {
                // Wait for the in-flight request
                const hints = await requestEntry.promise;

                // If the CURRENT request was canceled, return early to respect VS Code's token
                if (token.isCancellationRequested) {
                    return undefined;
                }

                if (!hints) {
                    return undefined;
                }

                // Return only hints in requested range
                return (hints as InlayHint[]).filter(
                    hint =>
                        hint.position.line >= range.start.line &&
                        hint.position.line <= range.end.line
                );
            } catch (error) {
                outputChannel.appendLine(
                    `[RETRY] Initial inlay hints request failed, entering retry flow: ${error}`
                );
                return retryOperation(
                    async () => {
                        const fullRange = new Range(0, 0, document.lineCount, 0);
                        const retryCts = new CancellationTokenSource();
                        try {
                            const result = next(document, fullRange, retryCts.token);
                            const hints = (await Promise.resolve(result)) as
                                | InlayHint[]
                                | null
                                | undefined;

                            if (token.isCancellationRequested) {
                                return undefined;
                            }

                            if (!hints) {
                                return undefined;
                            }

                            // Update cache after successful retry
                            inlayHintCache.set(uri, {
                                version: currentVersion,
                                hints: hints,
                            });

                            return hints.filter(
                                hint =>
                                    hint.position.line >= range.start.line &&
                                    hint.position.line <= range.end.line
                            );
                        } finally {
                            retryCts.dispose();
                        }
                    },
                    {
                        maxRetries: 3,
                        initialDelay: 500,
                        shouldRetry: isRetryableError,
                        onRetry: (attempt, err, delay) => {
                            outputChannel.appendLine(
                                `[RETRY] Inlay hints request failed (attempt ${attempt + 1}/3), retrying in ${delay}ms: ${err}`
                            );
                        },
                    }
                ).catch(() => undefined);
            }
        },
    };
}
