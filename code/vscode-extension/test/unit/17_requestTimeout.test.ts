import * as assert from 'assert';
import { workspace } from 'vscode';
import {
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    RequestTimeoutError,
    getRequestTimeoutMs,
    sendRequestWithTimeout,
    type RequestSender,
} from '../../src/lsp/requestTimeout';

/** Minimal fake matching the `workspace.getConfiguration(...).get(key, fallback)` shape used. */
function stubConfiguredTimeout(value: unknown): void {
    (workspace as unknown as { getConfiguration: (section: string) => unknown }).getConfiguration =
        () => ({
            get: (_key: string, fallback: unknown) => (value === undefined ? fallback : value),
        });
}

suite('getRequestTimeoutMs', () => {
    test('falls back to the default when unconfigured', () => {
        stubConfiguredTimeout(undefined);
        assert.strictEqual(getRequestTimeoutMs(), DEFAULT_REQUEST_TIMEOUT_SECONDS * 1000);
    });

    test('uses a valid configured value', () => {
        stubConfiguredTimeout(45);
        assert.strictEqual(getRequestTimeoutMs(), 45_000);
    });

    test('falls back to the default on a non-positive configured value', () => {
        stubConfiguredTimeout(0);
        assert.strictEqual(getRequestTimeoutMs(), DEFAULT_REQUEST_TIMEOUT_SECONDS * 1000);
    });

    test('falls back to the default on a non-numeric configured value', () => {
        stubConfiguredTimeout('not-a-number');
        assert.strictEqual(getRequestTimeoutMs(), DEFAULT_REQUEST_TIMEOUT_SECONDS * 1000);
    });
});

suite('sendRequestWithTimeout', () => {
    test('resolves with the server result when it answers before the timeout', async () => {
        const client: RequestSender = {
            sendRequest: async <T>() => ({ success: true }) as T,
        };

        const result = await sendRequestWithTimeout(
            client,
            'fangtype/insertType',
            ['file:///x.py', 0, 0],
            'Insert type annotation',
            50
        );

        assert.deepStrictEqual(result, { success: true });
    });

    test('does not cancel the token when the server answers in time', async () => {
        let capturedToken: { isCancellationRequested: boolean } | undefined;
        const client: RequestSender = {
            sendRequest: async <T>(_method: string, _params: unknown, token?: unknown) => {
                capturedToken = token as { isCancellationRequested: boolean };
                return { success: true } as T;
            },
        };

        await sendRequestWithTimeout(
            client,
            'fangtype/insertType',
            [],
            'Insert type annotation',
            50
        );

        assert.strictEqual(capturedToken?.isCancellationRequested, false);
    });

    test('rejects with RequestTimeoutError when the server never answers', async () => {
        const client: RequestSender = {
            sendRequest: () => new Promise(() => {}), // never resolves: simulates a hung server
        };

        await assert.rejects(
            sendRequestWithTimeout(
                client,
                'fangtype/insertTypesInFile',
                ['file:///x.py'],
                'Insert all type annotations',
                10
            ),
            (error: unknown) => {
                assert.ok(error instanceof RequestTimeoutError);
                assert.match(error.message, /Insert all type annotations timed out after/);
                return true;
            }
        );
    });

    test('cancels the token handed to sendRequest once the timeout fires', async () => {
        let capturedToken: { isCancellationRequested: boolean } | undefined;
        const client: RequestSender = {
            sendRequest: (_method, _params, token) => {
                capturedToken = token as { isCancellationRequested: boolean };
                return new Promise(() => {}); // never resolves: simulates a hung server
            },
        };

        await assert.rejects(
            sendRequestWithTimeout(client, 'fangtype/insertType', [], 'Insert type annotation', 10)
        );

        // The whole point of threading a token through: a timeout must cancel server-side work,
        // not just abandon the client-side promise.
        assert.strictEqual(capturedToken?.isCancellationRequested, true);
    });
});
