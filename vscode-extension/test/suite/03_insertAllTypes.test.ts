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

/**
 * Insert All Types Test Suite
 *
 * Tests for the "Insert All Types" command that annotates all unannotated
 * variables in a file at once.
 *
 * Note: In test mode (VSCODE_EXTENSION_TEST_MODE=true), the extension skips
 * the modal confirmation dialog to keep tests headless and deterministic.
 */

suite('Insert All Types Test Suite', () => {
    suiteSetup(async function () {
        this.timeout(45000);

        // Global warmup already handled in global.test.ts
        // Any suite-specific setup can go here
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

        // Execute command in test mode (modal confirmation is bypassed)
        const commandPromise = vscode.commands.executeCommand('autoType.insertAllTypes');

        // Wait for the preview to be generated
        await sleep(1500);

        // Command should complete without error
        await commandPromise;

        const annotations = extractTypeAnnotations(editor.document);
        assert.strictEqual(annotations.get('x'), 'int', 'x should be annotated');
        assert.strictEqual(annotations.get('name'), 'str', 'name should be annotated');
        assert.strictEqual(annotations.get('is_active'), 'bool', 'is_active should be annotated');

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

        // Execute command
        const commandPromise = vscode.commands.executeCommand('autoType.insertAllTypes');
        await sleep(1500);
        await commandPromise;

        // Verify already-annotated variables are preserved
        const annotations = extractTypeAnnotations(editor.document);
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

        await sleep(1000);

        // Execute command on file with no variables
        await vscode.commands.executeCommand('autoType.insertAllTypes');
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
        await sleep(1000);

        // Execute command - should show message about no types to insert
        await vscode.commands.executeCommand('autoType.insertAllTypes');
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

    test('Insert-all command modifies document in test mode', async function () {
        this.timeout(30000);

        const code = `a = 1
b = 2
c = 3
`;
        const editor = await openPythonFile(code);
        await waitForServerReadyForInsertion(editor, 3, 20000);

        // Execute insertAllTypes in test mode (confirmation is bypassed)
        await vscode.commands.executeCommand('autoType.insertAllTypes');
        await sleep(1000);

        const annotations = extractTypeAnnotations(editor.document);
        assert.strictEqual(annotations.get('a'), 'int', 'a should be annotated');
        assert.strictEqual(annotations.get('b'), 'int', 'b should be annotated');
        assert.strictEqual(annotations.get('c'), 'int', 'c should be annotated');

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
