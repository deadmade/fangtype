import { Range, CancellationTokenSource, InlayHint } from 'vscode';
import type { Middleware } from 'vscode-languageclient/node';

// In-flight requests per versioned URI: dedupes concurrent calls; the CTS cancels stale ones.
const inFlightRequests = new Map<
    string,
    { promise: Promise<InlayHint[] | null | undefined>; cts: CancellationTokenSource }
>();

// Track the latest version we've seen for each URI to cancel stale requests
const latestVersions = new Map<string, number>();

/**
 * Cancel in-flight inlay hint requests for a URI on close; the server owns the result cache.
 *
 * @param uri - Document URI to clean up
 */
export function clearInlayHintCache(uri: string): void {
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

/** Inlay hints: dedupe + cancel stale, filter to range; no client cache (empty would stick). */
export function createMiddleware(outputChannel: { appendLine: (msg: string) => void }): Middleware {
    return {
        provideInlayHints: async (document, range, token, next) => {
            const uri = document.uri.toString();
            const currentVersion = document.version;
            const versionedUri = `${uri}#${currentVersion}`;

            // 1. Manage version tracking and stale request cancellation
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

            // 2. Check in-flight requests to deduplicate
            let entry = inFlightRequests.get(versionedUri);
            if (!entry) {
                // No in-flight request yet: request full file range from server
                const fullRange = new Range(0, 0, document.lineCount, 0);

                // Own CTS so a canceled first client call doesn't kill the server request.
                const cts = new CancellationTokenSource();
                const result = next(document, fullRange, cts.token);

                // Ensure we have a Promise and filter out void
                const promise = Promise.resolve(result).then(
                    hints => hints ?? undefined
                ) as Promise<InlayHint[] | null | undefined>;

                entry = { promise, cts };
                inFlightRequests.set(versionedUri, entry);

                promise
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
                // Failure = no hints; VS Code re-requests next trigger, client restarts on crash.
                outputChannel.appendLine(`Inlay hints request failed: ${error}`);
                return undefined;
            }
        },
    };
}
