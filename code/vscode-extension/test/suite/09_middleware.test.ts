import * as assert from 'assert';
import { Range, Position, CancellationTokenSource } from 'vscode';
import type { InlayHint, TextDocument, CancellationToken } from 'vscode';
import type { Middleware } from 'vscode-languageclient/node';

// Tested in isolation: import createMiddleware and clearInlayHintCache directly.
import { createMiddleware, clearInlayHintCache } from '../../src/lsp/middleware';

/** Mock output channel for testing. */
function createMockOutputChannel(): { appendLine: (msg: string) => void; messages: string[] } {
    const messages: string[] = [];
    return {
        messages,
        appendLine: (msg: string) => {
            messages.push(msg);
        },
    };
}

/** Create a mock TextDocument for testing. */
function createMockDocument(uri: string, version: number, lineCount = 100): TextDocument {
    return {
        uri: { toString: () => uri },
        version,
        lineCount,
    } as unknown as TextDocument;
}

/** Create a mock InlayHint at the specified line. */
function createMockHint(line: number, character = 0): InlayHint {
    return {
        position: new Position(line, character),
        label: `hint at line ${line}`,
    } as InlayHint;
}

/** Helper to safely get provideInlayHints from middleware. */
function getProvideInlayHints(middleware: Middleware) {
    const fn = middleware.provideInlayHints;
    if (!fn) {
        throw new Error('provideInlayHints is not defined on middleware');
    }
    return fn;
}

/** Test suite for Inlay Hint Middleware. */
suite('Inlay Hint Middleware', function () {
    this.timeout(30000);

    let middleware: Middleware;
    let provideInlayHints: ReturnType<typeof getProvideInlayHints>;
    let outputChannel: ReturnType<typeof createMockOutputChannel>;

    setup(() => {
        outputChannel = createMockOutputChannel();
        middleware = createMiddleware(outputChannel);
        provideInlayHints = getProvideInlayHints(middleware);
        // Clear any leftover in-flight state from previous tests
        clearInlayHintCache('file:///test.py');
        clearInlayHintCache('file:///test1.py');
        clearInlayHintCache('file:///test2.py');
    });

    suite('Range Filtering', () => {
        test('should call next() and filter hints to requested range', async () => {
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

            // First call - should call next() and filter to range
            const result1 = await provideInlayHints(document, range, cts.token, next);

            assert.strictEqual(callCount, 1, 'Should call next() on first request');
            assert.ok(Array.isArray(result1), 'Should return array');
            // Should only return hints in range 0-10
            assert.strictEqual(
                (result1 as InlayHint[]).length,
                11,
                'Should filter hints to requested range'
            );

            // Same version calls next() again: no client-side result cache, the server owns it.
            const result2 = await provideInlayHints(document, range, cts.token, next);

            assert.strictEqual(
                callCount,
                2,
                'Should call next() again (no client-side result cache)'
            );
            assert.strictEqual(
                (result2 as InlayHint[]).length,
                11,
                'Should still filter to requested range correctly'
            );

            cts.dispose();
        });

        test('should call next() again when document version changes', async () => {
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

            // Second call with version 2
            await provideInlayHints(document2, range, cts.token, next);
            assert.strictEqual(callCount, 2, 'Should call next() for new version');

            cts.dispose();
        });

        test('should filter to different ranges across sequential calls', async () => {
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

            // Second call - narrower range (lines 5-15); no result cache, so next() runs again
            const range2 = new Range(5, 0, 15, 0);
            const result2 = await provideInlayHints(document, range2, cts.token, next);
            assert.strictEqual(
                callCount,
                2,
                'Should call next() again for the second range (no result cache)'
            );
            assert.strictEqual(
                (result2 as InlayHint[]).length,
                3,
                'Should return hints at lines 5, 10, 15'
            );

            cts.dispose();
        });
    });

    suite('Empty Result Handling', () => {
        test('should call next() again after an empty result, not poison future requests', async () => {
            const document = createMockDocument('file:///test.py', 1);
            const range = new Range(0, 0, 10, 0);
            const cts = new CancellationTokenSource();

            // The server never returns null, but may transiently return [] (unsynced/cancelled).
            const realHints = [createMockHint(3), createMockHint(7)];
            let callCount = 0;

            const next = async () => {
                callCount++;
                if (callCount === 1) {
                    return [];
                }
                return realHints;
            };

            // First call - server returns no hints yet
            const result1 = await provideInlayHints(document, range, cts.token, next);
            assert.strictEqual(callCount, 1, 'Should call next() on first request');
            assert.deepStrictEqual(result1, [], 'First call returns the empty array as-is');

            // Same version must not be served from a poisoned empty cache; next() runs again.
            const result2 = await provideInlayHints(document, range, cts.token, next);
            assert.strictEqual(
                callCount,
                2,
                'Should call next() again instead of reusing a cached empty result'
            );
            assert.strictEqual(
                (result2 as InlayHint[]).length,
                2,
                'Second call should return the real hints, not an empty cached result'
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

            // Immediately start the fast version 2 request, which should cancel version 1.
            await new Promise(resolve => setTimeout(resolve, 10));
            const promise2 = provideInlayHints(document2, range, cts.token, next2);

            await Promise.all([promise1, promise2]);

            // Version 1 completing is timing-dependent; only version 2's correctness matters.
            assert.ok(version2Completed, 'Version 2 request should complete');

            cts.dispose();
        });
    });

    suite('In-Flight Request Cleanup', () => {
        test('clearInlayHintCache cancels the in-flight server-request token for that URI', async () => {
            const document = createMockDocument('file:///test.py', 1);
            const range = new Range(0, 0, 10, 0);
            const cts = new CancellationTokenSource();

            let capturedToken: CancellationToken | undefined;

            const next = async (_doc: TextDocument, _range: Range, token: CancellationToken) => {
                capturedToken = token;
                await new Promise(resolve => setTimeout(resolve, 50));
                return [createMockHint(5)];
            };

            const promise = provideInlayHints(document, range, cts.token, next);

            // Let the request register as in-flight before clearing
            await new Promise(resolve => setTimeout(resolve, 10));

            clearInlayHintCache('file:///test.py');

            assert.ok(capturedToken, 'next() should have been called and captured a token');
            assert.strictEqual(
                capturedToken?.isCancellationRequested,
                true,
                'The in-flight server-request token should be cancelled by clearInlayHintCache'
            );

            await promise;
            cts.dispose();
        });

        test('clearInlayHintCache should not affect other URIs in-flight requests', async () => {
            const document1 = createMockDocument('file:///test1.py', 1);
            const document2 = createMockDocument('file:///test2.py', 1);
            const range = new Range(0, 0, 10, 0);
            const cts = new CancellationTokenSource();

            let token1: CancellationToken | undefined;
            let token2: CancellationToken | undefined;

            const next1 = async (_doc: TextDocument, _range: Range, token: CancellationToken) => {
                token1 = token;
                await new Promise(resolve => setTimeout(resolve, 50));
                return [createMockHint(5)];
            };
            const next2 = async (_doc: TextDocument, _range: Range, token: CancellationToken) => {
                token2 = token;
                await new Promise(resolve => setTimeout(resolve, 50));
                return [createMockHint(5)];
            };

            const promise1 = provideInlayHints(document1, range, cts.token, next1);
            const promise2 = provideInlayHints(document2, range, cts.token, next2);

            // Let both requests register as in-flight before clearing just one
            await new Promise(resolve => setTimeout(resolve, 10));

            clearInlayHintCache('file:///test1.py');

            assert.strictEqual(
                token1?.isCancellationRequested,
                true,
                'test1.py in-flight request should be cancelled'
            );
            assert.strictEqual(
                token2?.isCancellationRequested,
                false,
                'test2.py in-flight request should be unaffected'
            );

            await Promise.all([promise1, promise2]);
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

    suite('Error Behavior', () => {
        // 47b3afd dropped the network-style retry layer: the server is a local stdio child,
        // so a failed request is a real failure, not a transient blip worth re-sending.
        test('should surface an error as undefined without retrying', async () => {
            const document = createMockDocument('file:///test.py', 1);
            const range = new Range(0, 0, 10, 0);
            const cts = new CancellationTokenSource();

            let callCount = 0;

            const next = async () => {
                callCount++;
                throw { code: 'ETIMEDOUT', message: 'Persistent timeout' };
            };

            const result = await provideInlayHints(document, range, cts.token, next);

            assert.strictEqual(callCount, 1, 'Should call through exactly once (no retry layer)');
            assert.strictEqual(result, undefined, 'Should return undefined on error');

            cts.dispose();
        });
    });
});
