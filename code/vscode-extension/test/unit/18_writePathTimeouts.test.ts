import * as assert from 'assert';
import { window, workspace } from 'vscode';
import type { LanguageClient } from 'vscode-languageclient/node';
import type { TextEditor, OutputChannel } from 'vscode';
import { insertTypeAtCursor, insertAllTypesInFile } from '../../src/commands/insertCommands';
import { removeTypeAtCursor, removeAllTypesInFile } from '../../src/commands/removeCommands';

/**
 * Black-box regression for S6.4: every write-path command must route its `sendRequest` through
 * `sendRequestWithTimeout`, not call it directly. A direct `client.sendRequest(...)` call would
 * hang forever against the never-resolving fake client below and time out the *test*, rather
 * than resolving quickly with a surfaced error the way the timeout helper does.
 */

const TINY_TIMEOUT_SECONDS = 0.01; // 10ms: well under mocha's default per-test timeout

function stubTinyRequestTimeout(): void {
    (workspace as unknown as { getConfiguration: (section: string) => unknown }).getConfiguration =
        () => ({
            get: (_key: string, fallback: unknown) =>
                _key === 'requestTimeoutSeconds' ? TINY_TIMEOUT_SECONDS : fallback,
        });
}

/** A client whose sendRequest never resolves -- stands in for a hung server. */
function hungClient(): LanguageClient {
    return { sendRequest: () => new Promise(() => {}) } as unknown as LanguageClient;
}

function captureErrorMessages(): string[] {
    const messages: string[] = [];
    (window as unknown as { showErrorMessage: (msg: string) => undefined }).showErrorMessage = (
        msg: string
    ) => {
        messages.push(msg);
        return undefined;
    };
    (window as unknown as { showWarningMessage: (msg: string) => undefined }).showWarningMessage =
        () => undefined;
    (
        window as unknown as { showInformationMessage: (msg: string) => undefined }
    ).showInformationMessage = () => undefined;
    return messages;
}

const fakeOutputChannel = { appendLine: () => undefined } as unknown as OutputChannel;

suite('Write-path commands route through the request timeout helper', () => {
    setup(() => {
        stubTinyRequestTimeout();
    });

    test('insertTypeAtCursor surfaces a timeout error instead of hanging', async () => {
        const messages = captureErrorMessages();
        const editor = {
            document: { uri: { toString: () => 'file:///test.py' }, version: 1 },
            selection: { active: { line: 0, character: 0 } },
        } as unknown as TextEditor;

        await insertTypeAtCursor(editor, hungClient(), fakeOutputChannel);

        assert.ok(
            messages.some(m => /timed out/.test(m)),
            `expected a timeout error message, got: ${JSON.stringify(messages)}`
        );
    });

    test('insertAllTypesInFile surfaces a timeout error instead of hanging', async () => {
        const messages = captureErrorMessages();
        const editor = {
            document: { uri: { toString: () => 'file:///test.py' } },
        } as unknown as TextEditor;

        await insertAllTypesInFile(hungClient(), fakeOutputChannel, editor);

        assert.ok(
            messages.some(m => /timed out/.test(m)),
            `expected a timeout error message, got: ${JSON.stringify(messages)}`
        );
    });

    test('removeTypeAtCursor surfaces a timeout error instead of hanging', async () => {
        const messages = captureErrorMessages();
        const wordRange = { start: { line: 0, character: 0 }, end: { line: 0, character: 1 } };
        const editor = {
            document: {
                uri: { toString: () => 'file:///test.py' },
                version: 1,
                getWordRangeAtPosition: () => wordRange,
                getText: () => 'x',
                lineAt: () => ({ text: 'x: int = 1' }),
            },
            selection: { active: { line: 0, character: 0 } },
        } as unknown as TextEditor;

        await removeTypeAtCursor(editor, hungClient());

        assert.ok(
            messages.some(m => /timed out/.test(m)),
            `expected a timeout error message, got: ${JSON.stringify(messages)}`
        );
    });

    test('removeAllTypesInFile surfaces a timeout error instead of hanging', async () => {
        const messages = captureErrorMessages();
        const editor = {
            document: { languageId: 'python', uri: { toString: () => 'file:///test.py' } },
        };
        (window as unknown as { activeTextEditor: unknown }).activeTextEditor = editor;

        await removeAllTypesInFile(hungClient());

        assert.ok(
            messages.some(m => /timed out/.test(m)),
            `expected a timeout error message, got: ${JSON.stringify(messages)}`
        );
    });
});
