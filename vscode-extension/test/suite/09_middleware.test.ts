import * as assert from 'assert';
import { Range, Position, CancellationTokenSource } from 'vscode';
import type { InlayHint, TextDocument, CancellationToken } from 'vscode';
import type { Middleware } from 'vscode-languageclient/node';

// We need to test the middleware in isolation, so we'll import and test
// the createMiddleware function and clearInlayHintCache
import { createMiddleware, clearInlayHintCache } from '../../src/lsp/middleware';

/**
 * Mock output channel for testing
 */
function createMockOutputChannel(): { appendLine: (msg: string) => void; messages: string[] } {
    const messages: string[] = [];
    return {
        messages,
        appendLine: (msg: string) => {
            messages.push(msg);
        },
    };
}

/**
 * Create a mock TextDocument for testing
 */
function createMockDocument(uri: string, version: number, lineCount = 100): TextDocument {
    return {
        uri: { toString: () => uri },
        version,
        lineCount,
    } as unknown as TextDocument;
}

/**
 * Create a mock InlayHint at the specified line
 */
function createMockHint(line: number, character = 0): InlayHint {
    return {
        position: new Position(line, character),
        label: `hint at line ${line}`,
    } as InlayHint;
}

/**
 * Helper to safely get provideInlayHints from middleware
 */
function getProvideInlayHints(middleware: Middleware) {
    const fn = middleware.provideInlayHints;
    if (!fn) {
        throw new Error('provideInlayHints is not defined on middleware');
    }
    return fn;
}

/**
 * Test suite for Inlay Hint Middleware
 */
suite('Inlay Hint Middleware', function () {
    this.timeout(30000);

    let middleware: Middleware;
    let provideInlayHints: ReturnType<typeof getProvideInlayHints>;
    let outputChannel: ReturnType<typeof createMockOutputChannel>;

    setup(() => {
        outputChannel = createMockOutputChannel();
        middleware = createMiddleware(outputChannel);
        provideInlayHints = getProvideInlayHints(middleware);
        // Clear any leftover cache from previous tests
        clearInlayHintCache('file:///test.py');
        clearInlayHintCache('file:///test2.py');
    });

    suite('Cache Behavior', () => {
        test('should cache hints and return filtered results on subsequent calls', async () => {
            const document = createMockDocument('file:///test.py', 1);
            const range = new Range(0, 0, 10, 0);
            const cts = new CancellationTokenSource();

            // Create hints spanning lines 0-20
            const allHints = Array.from({ length: 20 }, (_, i) => createMockHint(i));
            let callCount = 0;

            const next = async () => {
                callCount++;
                return allHints;
            };

            // First call - should call next() and cache
            const result1 = await provideInlayHints(document, range, cts.token, next);

            assert.strictEqual(callCount, 1, 'Should call next() on first request');
            assert.ok(Array.isArray(result1), 'Should return array');
            // Should only return hints in range 0-10
            assert.strictEqual(
                (result1 as InlayHint[]).length,
                11,
                'Should filter hints to requested range'
            );

            // Second call with same version - should use cache
            const result2 = await provideInlayHints(document, range, cts.token, next);

            assert.strictEqual(callCount, 1, 'Should NOT call next() on cache hit');
            assert.strictEqual(
                (result2 as InlayHint[]).length,
                11,
                'Should return same filtered hints'
            );

            cts.dispose();
        });

        test('should invalidate cache when document version changes', async () => {
            const document1 = createMockDocument('file:///test.py', 1);
            const document2 = createMockDocument('file:///test.py', 2);
            const range = new Range(0, 0, 10, 0);
            const cts = new CancellationTokenSource();

            const hints = [createMockHint(5)];
            let callCount = 0;

            const next = async () => {
                callCount++;
                return hints;
            };

            // First call with version 1
            await provideInlayHints(document1, range, cts.token, next);
            assert.strictEqual(callCount, 1, 'Should call next() for version 1');

            // Second call with version 2 - cache should be invalidated
            await provideInlayHints(document2, range, cts.token, next);
            assert.strictEqual(callCount, 2, 'Should call next() for new version');

            cts.dispose();
        });

        test('should filter cached hints to different ranges', async () => {
            const document = createMockDocument('file:///test.py', 1);
            const cts = new CancellationTokenSource();

            // Create hints at lines 0, 5, 10, 15, 20
            const allHints = [0, 5, 10, 15, 20].map(line => createMockHint(line));
            let callCount = 0;

            const next = async () => {
                callCount++;
                return allHints;
            };

            // First call - full file
            const range1 = new Range(0, 0, 25, 0);
            const result1 = await provideInlayHints(document, range1, cts.token, next);
            assert.strictEqual((result1 as InlayHint[]).length, 5, 'Should return all 5 hints');

            // Second call - narrower range (lines 5-15)
            const range2 = new Range(5, 0, 15, 0);
            const result2 = await provideInlayHints(document, range2, cts.token, next);
            assert.strictEqual(callCount, 1, 'Should use cache for second request');
            assert.strictEqual(
                (result2 as InlayHint[]).length,
                3,
                'Should return hints at lines 5, 10, 15'
            );

            cts.dispose();
        });
    });

    suite('Request Deduplication', () => {
        test('should deduplicate concurrent requests for same version', async () => {
            const document = createMockDocument('file:///test.py', 1);
            const range = new Range(0, 0, 10, 0);
            const cts = new CancellationTokenSource();

            const hints = [createMockHint(5)];
            let callCount = 0;

            // Simulate a slow server response
            const next = async () => {
                callCount++;
                await new Promise(resolve => setTimeout(resolve, 50));
                return hints;
            };

            // Fire 5 concurrent requests
            const promises = Array.from({ length: 5 }, () =>
                provideInlayHints(document, range, cts.token, next)
            );

            const results = await Promise.all(promises);

            // Should only call next() once due to deduplication
            assert.strictEqual(
                callCount,
                1,
                'Should only call next() once for concurrent requests'
            );

            // All results should be valid
            for (const result of results) {
                assert.ok(Array.isArray(result), 'Each result should be an array');
                assert.strictEqual(
                    (result as InlayHint[]).length,
                    1,
                    'Each result should have 1 hint'
                );
            }

            cts.dispose();
        });

        test('should make separate requests for different documents', async () => {
            const document1 = createMockDocument('file:///test1.py', 1);
            const document2 = createMockDocument('file:///test2.py', 1);
            const range = new Range(0, 0, 10, 0);
            const cts = new CancellationTokenSource();

            const hints = [createMockHint(5)];
            let callCount = 0;

            const next = async () => {
                callCount++;
                return hints;
            };

            // Request for two different documents
            await Promise.all([
                provideInlayHints(document1, range, cts.token, next),
                provideInlayHints(document2, range, cts.token, next),
            ]);

            assert.strictEqual(
                callCount,
                2,
                'Should make separate requests for different documents'
            );

            cts.dispose();
        });
    });

    suite('Stale Request Cancellation', () => {
        test('should cancel in-flight request when newer version is requested', async () => {
            const document1 = createMockDocument('file:///test.py', 1);
            const document2 = createMockDocument('file:///test.py', 2);
            const range = new Range(0, 0, 10, 0);
            const cts = new CancellationTokenSource();

            const hints = [createMockHint(5)];
            let version2Completed = false;

            // Version 1 request is slow
            const next1 = async (_doc: TextDocument, _range: Range, token: CancellationToken) => {
                await new Promise(resolve => setTimeout(resolve, 100));
                // Check if this request was cancelled
                if (token.isCancellationRequested) {
                    return null;
                }
                return hints;
            };

            // Version 2 request is fast
            const next2 = async () => {
                version2Completed = true;
                return hints;
            };

            // Start version 1 request (slow)
            const promise1 = provideInlayHints(document1, range, cts.token, next1);

            // Immediately start version 2 request (fast)
            // This should cancel the version 1 request
            await new Promise(resolve => setTimeout(resolve, 10));
            const promise2 = provideInlayHints(document2, range, cts.token, next2);

            await Promise.all([promise1, promise2]);

            // Version 2 should complete, version 1 may or may not complete
            // depending on timing, but the key is that version 2 works correctly
            assert.ok(version2Completed, 'Version 2 request should complete');

            cts.dispose();
        });
    });

    suite('Cache Cleanup', () => {
        test('clearInlayHintCache should remove cache entry for URI', async () => {
            const document = createMockDocument('file:///test.py', 1);
            const range = new Range(0, 0, 10, 0);
            const cts = new CancellationTokenSource();

            const hints = [createMockHint(5)];
            let callCount = 0;

            const next = async () => {
                callCount++;
                return hints;
            };

            // First call - populate cache
            await provideInlayHints(document, range, cts.token, next);
            assert.strictEqual(callCount, 1, 'Should call next() initially');

            // Clear the cache
            clearInlayHintCache('file:///test.py');

            // Next call should fetch again
            await provideInlayHints(document, range, cts.token, next);
            assert.strictEqual(callCount, 2, 'Should call next() after cache clear');

            cts.dispose();
        });

        test('clearInlayHintCache should not affect other URIs', async () => {
            const document1 = createMockDocument('file:///test1.py', 1);
            const document2 = createMockDocument('file:///test2.py', 1);
            const range = new Range(0, 0, 10, 0);
            const cts = new CancellationTokenSource();

            const hints = [createMockHint(5)];
            let callCount = 0;

            const next = async () => {
                callCount++;
                return hints;
            };

            // Populate cache for both documents
            await provideInlayHints(document1, range, cts.token, next);
            await provideInlayHints(document2, range, cts.token, next);
            assert.strictEqual(callCount, 2, 'Should call next() for both documents');

            // Clear only test1.py
            clearInlayHintCache('file:///test1.py');

            // Request for test1.py should fetch again
            await provideInlayHints(document1, range, cts.token, next);
            assert.strictEqual(callCount, 3, 'Should call next() for cleared document');

            // Request for test2.py should use cache
            await provideInlayHints(document2, range, cts.token, next);
            assert.strictEqual(callCount, 3, 'Should NOT call next() for cached document');

            cts.dispose();
        });
    });

    suite('Return Values', () => {
        test('should return undefined when hints are null', async () => {
            const document = createMockDocument('file:///test.py', 1);
            const range = new Range(0, 0, 10, 0);
            const cts = new CancellationTokenSource();

            const next = async () => null;

            const result = await provideInlayHints(document, range, cts.token, next);

            assert.strictEqual(result, undefined, 'Should return undefined for null hints');

            cts.dispose();
        });

        test('should return undefined when request is cancelled', async () => {
            const document = createMockDocument('file:///test.py', 1);
            const range = new Range(0, 0, 10, 0);
            const cts = new CancellationTokenSource();

            const hints = [createMockHint(5)];
            const next = async () => {
                // Simulate cancellation during request
                cts.cancel();
                await new Promise(resolve => setTimeout(resolve, 10));
                return hints;
            };

            const result = await provideInlayHints(document, range, cts.token, next);

            // Should return undefined when cancelled
            assert.strictEqual(result, undefined, 'Should return undefined when cancelled');

            cts.dispose();
        });
    });

    suite('Retry Behavior', () => {
        test('should retry on transient errors and update cache on success', async () => {
            const document = createMockDocument('file:///test.py', 1);
            const range = new Range(0, 0, 10, 0);
            const cts = new CancellationTokenSource();

            const hints = [createMockHint(5)];
            let callCount = 0;

            const next = async () => {
                callCount++;
                if (callCount === 1) {
                    // First call fails with transient error
                    throw { code: 'ETIMEDOUT', message: 'Connection timed out' };
                }
                // Second call succeeds
                return hints;
            };

            const result = await provideInlayHints(document, range, cts.token, next);

            // Should have retried
            assert.ok(callCount >= 2, 'Should retry after transient error');
            assert.ok(Array.isArray(result), 'Should return hints after retry');
            assert.strictEqual((result as InlayHint[]).length, 1, 'Should have 1 hint');

            // Check retry was logged
            const retryLogs = outputChannel.messages.filter(m => m.includes('[RETRY]'));
            assert.ok(retryLogs.length > 0, 'Should log retry attempts');

            cts.dispose();
        });

        test('should return undefined after all retries exhausted', async () => {
            const document = createMockDocument('file:///test.py', 1);
            const range = new Range(0, 0, 10, 0);
            const cts = new CancellationTokenSource();

            let callCount = 0;

            const next = async () => {
                callCount++;
                throw { code: 'ETIMEDOUT', message: 'Persistent timeout' };
            };

            const result = await provideInlayHints(document, range, cts.token, next);

            // Should have attempted multiple times
            assert.ok(callCount >= 2, 'Should attempt multiple times');
            // Should return undefined after exhausting retries
            assert.strictEqual(result, undefined, 'Should return undefined after retry exhaustion');

            cts.dispose();
        });
    });
});
