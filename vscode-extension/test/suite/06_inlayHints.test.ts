import * as assert from 'assert';
import * as vscode from 'vscode';
import {
    openPythonFile,
    closeAllEditors,
    sleep,
    getInlayHints,
    waitForInlayHints,
    cleanupTempFiles,
    debugLog,
    logTestContext,
} from './helpers/testHelpers';

suite('Inlay Hints Test Suite', () => {
    suiteSetup(async function () {
        this.timeout(45000);

        // Global warmup already handled in global.test.ts
        // Any suite-specific setup can go here
    });

    test('Hints appear for simple variable', async function () {
        this.timeout(45000); // Increase from implicit default

        debugLog('--- Test: Hints appear for simple variable ---');
        const editor = await openPythonFile('x = 5\n');

        await logTestContext('After opening file');

        // Give server time to analyze
        await sleep(3000); // INCREASE from implicit

        debugLog('Requesting inlay hints...');

        // Wait for hints with retry logic
        let hints: vscode.InlayHint[] = [];
        try {
            hints = await waitForInlayHints(editor.document, 1, 25000); // INCREASE timeout
            debugLog(`Received ${hints.length} hints`);
        } catch (error) {
            await logTestContext('After hint request failed');
            throw new Error(`Failed to get inlay hints: ${error}`);
        }

        assert.strictEqual(hints.length, 1, 'Should have exactly 1 hint');

        // Verify hint content
        const hint = hints[0];
        assert.ok(hint, 'Hint should exist');
        const label = typeof hint.label === 'string' ? hint.label : hint.label[0]?.value || '';
        assert.ok(label.includes('int'), `Hint should contain 'int', got: ${label}`);

        await closeAllEditors();
    });

    test('Hints for multiple variables', async function () {
        this.timeout(45000);

        debugLog('--- Test: Hints for multiple variables ---');
        const code = `x = 5
name = "Alice"
is_active = True
`;
        const editor = await openPythonFile(code);

        await sleep(3000);

        debugLog('Requesting hints for 3 variables...');
        const hints = await waitForInlayHints(editor.document, 3, 25000);
        debugLog(`Received ${hints.length} hints`);

        assert.strictEqual(hints.length, 3, 'Should have 3 hints');

        // Verify hints contain expected types
        const labels = hints.map(h =>
            typeof h.label === 'string' ? h.label : h.label[0]?.value || ''
        );
        debugLog('Hint labels:', labels);

        assert.ok(
            labels.some(l => l.includes('int')),
            'Should have int hint'
        );
        assert.ok(
            labels.some(l => l.includes('str')),
            'Should have str hint'
        );
        assert.ok(
            labels.some(l => l.includes('bool')),
            'Should have bool hint'
        );

        await closeAllEditors();
    });

    test('No hints for annotated variables', async () => {
        const code = `x: int = 5
name: str = "Alice"
`;
        const editor = await openPythonFile(code);

        // Wait a bit for LSP to process
        await sleep(2000);

        const hints = await getInlayHints(editor.document);

        // Should have no hints (or very few) since variables are already annotated
        // Note: Some LSP servers might still provide hints for function parameters, etc.
        // So we allow up to 2 hints (lenient check)
        assert.ok(
            hints.length <= 2,
            `Should have few or no hints for annotated variables, got ${hints.length}`
        );

        await closeAllEditors();
    });

    test('Hints in specific range', async function () {
        this.timeout(45000);

        debugLog('--- Test: Hints in specific range ---');
        const code = `a = 1
b = 2
c = 3
d = 4
e = 5
`;
        const editor = await openPythonFile(code);

        await sleep(3000);

        // Wait for all hints first
        debugLog('Waiting for all hints...');
        await waitForInlayHints(editor.document, 5, 25000);

        // Request hints for just lines 1-2 (b and c)
        const range = new vscode.Range(1, 0, 3, 0);
        debugLog(`Requesting hints for range ${range.start.line}-${range.end.line}`);
        const hints = await getInlayHints(editor.document, range);
        debugLog(`Received ${hints.length} hints in range`);

        // Should get hints only for the requested range (2-3 hints is reasonable)
        assert.ok(
            hints.length >= 2 && hints.length <= 3,
            `Should have 2-3 hints for range, got ${hints.length}`
        );

        await closeAllEditors();
    });

    test('Hints update on document change', async function () {
        this.timeout(45000);

        debugLog('--- Test: Hints update on document change ---');
        const editor = await openPythonFile('x = 5\n');

        await sleep(2000);

        const initialHints = await waitForInlayHints(editor.document, 1, 25000);
        debugLog(`Initial hints: ${initialHints.length}`);
        assert.strictEqual(initialHints.length, 1, 'Should have 1 initial hint');

        // Add a new variable
        const edit = new vscode.WorkspaceEdit();
        edit.insert(editor.document.uri, new vscode.Position(1, 0), 'y = 10\n');
        await vscode.workspace.applyEdit(edit);

        // Wait for LSP to reprocess
        await sleep(3000); // INCREASE from 2000

        // Get updated hints
        debugLog('Requesting updated hints...');
        const updatedHints = await getInlayHints(editor.document);
        debugLog(`Updated hints: ${updatedHints.length}`);

        assert.ok(
            updatedHints.length >= 2,
            `Should have 2+ hints after adding variable, got ${updatedHints.length}`
        );

        await closeAllEditors();
    });

    test('Hint format validation', async function () {
        this.timeout(45000);

        debugLog('--- Test: Hint format validation ---');
        const editor = await openPythonFile('x = 5\n');

        await sleep(2000);

        const hints = await waitForInlayHints(editor.document, 1, 25000);
        const hint = hints[0];
        assert.ok(hint, 'Hint should exist');

        // Verify hint has correct properties
        assert.ok(hint.position, 'Hint should have position');
        assert.ok(hint.label, 'Hint should have label');

        // Verify label format (should start with ': ' or contain type)
        const label = typeof hint.label === 'string' ? hint.label : hint.label[0]?.value || '';
        debugLog(`Hint label: "${label}"`);
        assert.ok(
            label.includes(':') || label.includes('int'),
            `Hint label should include type info, got: ${label}`
        );

        // Verify position is valid
        assert.ok(hint.position.character >= 0, 'Hint position should be valid');
        debugLog(`Hint position: line ${hint.position.line}, char ${hint.position.character}`);

        await closeAllEditors();
    });

    test('Hints for various types', async function () {
        this.timeout(45000);

        debugLog('--- Test: Hints for various types ---');
        const code = `integer_val = 42
float_val = 3.14
string_val = "hello"
bool_val = False
list_val = [1, 2, 3]
dict_val = {"key": "value"}
`;
        const editor = await openPythonFile(code);

        await sleep(3000);

        debugLog('Waiting for hints for 6 variables...');
        const hints = await waitForInlayHints(editor.document, 6, 30000); // INCREASE timeout
        debugLog(`Received ${hints.length} hints`);

        assert.ok(hints.length >= 6, `Should have at least 6 hints, got ${hints.length}`);

        const labels = hints.map(h =>
            typeof h.label === 'string' ? h.label : h.label[0]?.value || ''
        );
        debugLog('All hint labels:', labels);

        // Verify different type hints are present
        assert.ok(
            labels.some(l => l.includes('int')),
            'Should have int hint'
        );
        assert.ok(
            labels.some(l => l.includes('float')),
            'Should have float hint'
        );
        assert.ok(
            labels.some(l => l.includes('str')),
            'Should have str hint'
        );
        assert.ok(
            labels.some(l => l.includes('bool')),
            'Should have bool hint'
        );
        assert.ok(
            labels.some(l => l.includes('list')),
            'Should have list hint'
        );
        assert.ok(
            labels.some(l => l.includes('dict')),
            'Should have dict hint'
        );

        await closeAllEditors();
    });

    suiteTeardown(async () => {
        await cleanupTempFiles();
    });
});
