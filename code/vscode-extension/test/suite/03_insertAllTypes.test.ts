import * as assert from 'assert';
import * as vscode from 'vscode';
import {
    openPythonFile,
    closeAllEditors,
    sleep,
    getDocumentText,
    waitForInlayHints,
    retryOperation,
    debugLog,
    cleanupTempFiles,
    waitForServerReadyForInsertion,
    extractTypeAnnotations,
} from './helpers/testHelpers';

/** Insert-all diff preview uses a read-only fangtype-preview doc, not a lingering untitled tab. */

const PREVIEW_SCHEME = 'fangtype-preview';

suite('Insert All Types Test Suite', () => {
    async function findPreviewDocument(excludedUri: vscode.Uri): Promise<vscode.TextDocument> {
        await retryOperation(
            async () => {
                const previewDoc = vscode.workspace.textDocuments.find(
                    doc =>
                        doc.uri.toString() !== excludedUri.toString() &&
                        doc.uri.scheme === PREVIEW_SCHEME
                );

                if (!previewDoc) {
                    throw new Error('Preview document not opened yet');
                }

                return previewDoc;
            },
            5,
            500
        );

        const previewDoc = vscode.workspace.textDocuments.find(
            doc =>
                doc.uri.toString() !== excludedUri.toString() && doc.uri.scheme === PREVIEW_SCHEME
        );

        assert.ok(previewDoc, 'Expected a fangtype-preview virtual document to be opened');
        assert.strictEqual(
            previewDoc.isUntitled,
            false,
            'Preview must not be an untitled document (those linger as a second tab)'
        );
        return previewDoc;
    }

    suiteSetup(async function () {
        this.timeout(45000);

        // Global warmup lives in global.test.ts; suite-specific setup goes here.
    });

    test('Preview insertions for multiple unannotated variables', async function () {
        this.timeout(45000);

        const code = `x = 5
name = "Alice"
is_active = True
`;
        const editor = await openPythonFile(code);

        debugLog('Waiting for inlay hints for multiple variables...');
        // Wait for inlay hints to appear (should have 3)
        const hints = await waitForServerReadyForInsertion(editor, 3, 20000);

        // Verify we have hints for all three variables
        assert.ok(hints.length >= 3, `Expected at least 3 inlay hints, got ${hints.length}`);

        debugLog(`Got ${hints.length} inlay hints`);

        const originalText = editor.document.getText();
        const commandPromise = vscode.commands.executeCommand('fangtype.insertAllTypes');

        await commandPromise;
        const previewDocument = await findPreviewDocument(editor.document.uri);

        assert.strictEqual(
            editor.document.getText(),
            originalText,
            'Original document should remain unchanged'
        );

        const annotations = extractTypeAnnotations(previewDocument);
        assert.strictEqual(annotations.get('x'), 'int', 'Preview should annotate x');
        assert.strictEqual(annotations.get('name'), 'str', 'Preview should annotate name');
        assert.strictEqual(
            annotations.get('is_active'),
            'bool',
            'Preview should annotate is_active'
        );

        await closeAllEditors();
    });

    test('Command detects already annotated vs unannotated variables', async function () {
        this.timeout(45000);

        const code = `x: int = 5
name: str = "Alice"
unannotated = 42
another = "test"
`;
        const editor = await openPythonFile(code);

        debugLog('Waiting for hints for mixed annotated/unannotated...');
        // Wait for hints (should only be for unannotated variables: 2 hints)
        await retryOperation(
            async () => {
                const h = await waitForInlayHints(editor.document, 2, 15000);
                if (h.length < 2) throw new Error(`Only got ${h.length} hints`);
                return h;
            },
            3,
            1000
        );

        const originalText = editor.document.getText();
        await vscode.commands.executeCommand('fangtype.insertAllTypes');
        const previewDocument = await findPreviewDocument(editor.document.uri);

        // Verify already-annotated variables are preserved
        assert.strictEqual(
            editor.document.getText(),
            originalText,
            'Original document should remain unchanged'
        );

        const annotations = extractTypeAnnotations(previewDocument);
        assert.strictEqual(annotations.get('x'), 'int', 'Existing annotation should be preserved');
        assert.strictEqual(
            annotations.get('name'),
            'str',
            'Existing annotation should be preserved'
        );
        assert.strictEqual(
            annotations.get('unannotated'),
            'int',
            'Unannotated variable should be annotated'
        );
        assert.strictEqual(
            annotations.get('another'),
            'str',
            'Unannotated variable should be annotated'
        );

        await closeAllEditors();
    });

    test('Empty file with no variables shows info message', async function () {
        this.timeout(30000);

        const editor = await openPythonFile('# Just a comment\n');

        // Execute command on file with no variables
        await vscode.commands.executeCommand('fangtype.insertAllTypes');
        await sleep(500);

        // Document should remain unchanged
        const text = getDocumentText(editor.document);
        assert.strictEqual(text.trim(), '# Just a comment', 'Document should remain unchanged');

        await closeAllEditors();
    });

    test('File with only annotated variables shows appropriate message', async function () {
        this.timeout(30000);

        const code = `x: int = 5
name: str = "Alice"
items: list[int] = [1, 2, 3]
`;
        const editor = await openPythonFile(code);
        // Execute command - should show message about no types to insert
        await vscode.commands.executeCommand('fangtype.insertAllTypes');
        await sleep(500);

        // Document should remain unchanged (all already annotated)
        const text = getDocumentText(editor.document);
        assert.ok(text.includes('x: int = 5'), 'Existing annotation should be preserved');
        assert.ok(text.includes('name: str = "Alice"'), 'Existing annotation should be preserved');

        await closeAllEditors();
    });

    test('Inlay hints generated for various types', async function () {
        this.timeout(45000);

        const code = `integer_val = 42
float_val = 3.14
string_val = "hello"
bool_val = False
list_val = [1, 2, 3]
dict_val = {"key": "value"}
`;
        const editor = await openPythonFile(code);

        debugLog('Waiting for hints for various types...');
        // Wait for hints for all 6 variables
        const hints = await waitForServerReadyForInsertion(editor, 6, 25000);

        // Verify we got hints for all variables
        assert.ok(
            hints.length >= 6,
            `Expected at least 6 inlay hints for various types, got ${hints.length}`
        );

        // Verify hints contain expected types
        const hintLabels = hints.map(h =>
            typeof h.label === 'string' ? h.label : (h.label[0]?.value ?? '')
        );
        debugLog('Hint labels:', hintLabels);

        // Check for expected type hints
        assert.ok(
            hintLabels.some(l => l.includes('int')),
            'Should have int type hint'
        );
        assert.ok(
            hintLabels.some(l => l.includes('float')),
            'Should have float type hint'
        );
        assert.ok(
            hintLabels.some(l => l.includes('str')),
            'Should have str type hint'
        );
        assert.ok(
            hintLabels.some(l => l.includes('bool')),
            'Should have bool type hint'
        );
        assert.ok(
            hintLabels.some(l => l.includes('list')),
            'Should have list type hint'
        );
        assert.ok(
            hintLabels.some(l => l.includes('dict')),
            'Should have dict type hint'
        );

        await closeAllEditors();
    });

    test('Insert-all command opens preview diff without modifying the source document', async function () {
        this.timeout(30000);

        const code = `a = 1
b = 2
c = 3
`;
        const editor = await openPythonFile(code);
        await waitForServerReadyForInsertion(editor, 3, 20000);

        const originalText = editor.document.getText();
        await vscode.commands.executeCommand('fangtype.insertAllTypes');
        const previewDocument = await findPreviewDocument(editor.document.uri);

        assert.strictEqual(
            editor.document.getText(),
            originalText,
            'Source document should not be modified when opening preview'
        );

        const annotations = extractTypeAnnotations(previewDocument);
        assert.strictEqual(annotations.get('a'), 'int', 'Preview should annotate a');
        assert.strictEqual(annotations.get('b'), 'int', 'Preview should annotate b');
        assert.strictEqual(annotations.get('c'), 'int', 'Preview should annotate c');

        await closeAllEditors();
    });

    test('Insert-all preview does not leave a lingering untitled document', async function () {
        this.timeout(30000);

        const code = `p = 1
q = 2
`;
        const editor = await openPythonFile(code);
        await waitForServerReadyForInsertion(editor, 2, 20000);

        const untitledBefore = vscode.workspace.textDocuments.filter(doc => doc.isUntitled).length;

        await vscode.commands.executeCommand('fangtype.insertAllTypes');
        const previewDocument = await findPreviewDocument(editor.document.uri);

        // The preview content must still be correct...
        const annotations = extractTypeAnnotations(previewDocument);
        assert.strictEqual(annotations.get('p'), 'int', 'Preview should annotate p');
        assert.strictEqual(annotations.get('q'), 'int', 'Preview should annotate q');

        // ...but the command must NOT have created any new untitled document.
        const untitledAfter = vscode.workspace.textDocuments.filter(doc => doc.isUntitled).length;
        assert.strictEqual(
            untitledAfter,
            untitledBefore,
            'Insert-all must not open an untitled document as a second tab'
        );

        await closeAllEditors();
    });

    test('Verify annotation extraction helper works correctly', async function () {
        this.timeout(30000);

        // This test verifies our test helper works correctly
        const code = `x: int = 5
name: str = "Alice"
unannotated = 42
`;
        const editor = await openPythonFile(code);
        await sleep(500);

        const annotations = extractTypeAnnotations(editor.document);

        // Should find the annotated variables
        assert.strictEqual(annotations.get('x'), 'int', 'Should extract x: int');
        assert.strictEqual(annotations.get('name'), 'str', 'Should extract name: str');

        // unannotated should not be in the map
        assert.strictEqual(
            annotations.has('unannotated'),
            false,
            'Unannotated variable should not appear in extraction'
        );

        await closeAllEditors();
    });

    suiteTeardown(async () => {
        await cleanupTempFiles();
    });
});
