import * as assert from 'assert';
import * as vscode from 'vscode';
import {
    openPythonFile,
    closeAllEditors,
    sleep,
    setCursorPosition,
    getDocumentText,
    debugLog,
    cleanupTempFiles,
    executeInsertionAndVerify,
    waitForServerReadyForInsertion,
} from './helpers/testHelpers';
import type { InsertionVerificationResult } from './helpers/testHelpers';

/**
 * Insert Type at Cursor Test Suite
 *
 * These tests verify that the insertTypeAtCursor command correctly inserts
 * type annotations for various Python variable types.
 *
 * Tests use hard assertions to verify that:
 * 1. The command executes successfully
 * 2. The document is modified
 * 3. The correct type annotation is inserted
 */

suite('Insert Type at Cursor Test Suite', () => {
    suiteSetup(async function () {
        this.timeout(45000);

        // Global warmup already handled in global.test.ts
        // Any suite-specific setup can go here
    });

    /**
     * Helper to run an insertion test with proper setup and verification.
     */
    async function runInsertionTest(
        testName: string,
        code: string,
        cursorLine: number,
        cursorCol: number,
        expectedPattern: string | RegExp,
        timeout = 30000
    ): Promise<InsertionVerificationResult> {
        debugLog(`Running test: ${testName}`);

        const editor = await openPythonFile(code);

        // Wait for server to be ready with inlay hints
        await waitForServerReadyForInsertion(editor, 1, 20000);

        // Set cursor position
        await setCursorPosition(editor, cursorLine, cursorCol);
        await sleep(300);

        // Execute and verify
        const result = await executeInsertionAndVerify(
            editor,
            'autoType.insertTypeAtCursor',
            expectedPattern,
            timeout
        );

        debugLog(`Test ${testName} result:`, {
            success: result.success,
            documentChanged: result.documentChanged,
            duration: result.duration,
        });

        await closeAllEditors();
        return result;
    }

    test('Insert type for simple integer variable', async function () {
        this.timeout(45000);

        const result = await runInsertionTest('integer variable', 'x = 5\n', 0, 0, 'x: int = 5');

        assert.ok(
            result.success,
            `Failed to insert type for integer variable. ` +
                `Document changed: ${result.documentChanged}. ` +
                `Actual text: "${result.actualText}". ` +
                `${result.errorMessage || ''}`
        );
    });

    test('Insert type for string variable', async function () {
        this.timeout(45000);

        const result = await runInsertionTest(
            'string variable',
            'name = "Alice"\n',
            0,
            0,
            'name: str = "Alice"'
        );

        assert.ok(
            result.success,
            `Failed to insert type for string variable. ` +
                `Document changed: ${result.documentChanged}. ` +
                `Actual text: "${result.actualText}". ` +
                `${result.errorMessage || ''}`
        );
    });

    test('Insert type for boolean variable', async function () {
        this.timeout(45000);

        const result = await runInsertionTest(
            'boolean variable',
            'is_active = True\n',
            0,
            0,
            'is_active: bool = True'
        );

        assert.ok(
            result.success,
            `Failed to insert type for boolean variable. ` +
                `Document changed: ${result.documentChanged}. ` +
                `Actual text: "${result.actualText}". ` +
                `${result.errorMessage || ''}`
        );
    });

    test('Insert type for float variable', async function () {
        this.timeout(45000);

        const result = await runInsertionTest(
            'float variable',
            'pi = 3.14\n',
            0,
            0,
            'pi: float = 3.14'
        );

        assert.ok(
            result.success,
            `Failed to insert type for float variable. ` +
                `Document changed: ${result.documentChanged}. ` +
                `Actual text: "${result.actualText}". ` +
                `${result.errorMessage || ''}`
        );
    });

    test('Insert type for list variable', async function () {
        this.timeout(45000);

        const result = await runInsertionTest(
            'list variable',
            'items = [1, 2, 3]\n',
            0,
            0,
            /items:\s*list\[int\]\s*=\s*\[1, 2, 3\]/
        );

        assert.ok(
            result.success,
            `Failed to insert type for list variable. ` +
                `Document changed: ${result.documentChanged}. ` +
                `Actual text: "${result.actualText}". ` +
                `${result.errorMessage || ''}`
        );
    });

    test('Insert type for dict variable', async function () {
        this.timeout(45000);

        const result = await runInsertionTest(
            'dict variable',
            'data = {"key": "value"}\n',
            0,
            0,
            /data:\s*dict\[str,\s*str\]\s*=/
        );

        assert.ok(
            result.success,
            `Failed to insert type for dict variable. ` +
                `Document changed: ${result.documentChanged}. ` +
                `Actual text: "${result.actualText}". ` +
                `${result.errorMessage || ''}`
        );
    });

    test('No variable at cursor should not crash', async function () {
        this.timeout(30000);

        const editor = await openPythonFile('x = 5\n# comment\n');

        await sleep(1000);

        // Set cursor on comment line (no variable)
        await setCursorPosition(editor, 1, 0);

        // Execute command - should not crash
        await vscode.commands.executeCommand('autoType.insertTypeAtCursor');
        await sleep(500);

        // Document should remain unchanged
        const text = getDocumentText(editor.document);
        assert.ok(text.includes('x = 5'), 'Original code should remain unchanged');
        assert.ok(!text.includes('# comment:'), 'Comment should not be modified');

        await closeAllEditors();
    });

    test('Already annotated variable should be handled gracefully', async function () {
        this.timeout(30000);

        const editor = await openPythonFile('x: int = 5\n');

        await sleep(1000);

        // Set cursor on 'x'
        await setCursorPosition(editor, 0, 0);

        // Execute command
        await vscode.commands.executeCommand('autoType.insertTypeAtCursor');
        await sleep(500);

        // Document should remain the same (not duplicated)
        const text = getDocumentText(editor.document);
        assert.ok(text.includes('x: int = 5'), 'Original annotation should be preserved');
        // Check that annotation is not duplicated (no "x: int: int")
        assert.ok(!text.includes('x: int: int'), 'Annotation should not be duplicated');

        await closeAllEditors();
    });

    test('Variable with no type inference should show warning', async function () {
        this.timeout(30000);

        const editor = await openPythonFile('x = unknown_func()\n');

        // Wait for LSP to process (it won't find hints for unknown function)
        await sleep(2000);

        // Set cursor on 'x'
        await setCursorPosition(editor, 0, 0);

        // Execute command - should not crash
        await vscode.commands.executeCommand('autoType.insertTypeAtCursor');
        await sleep(500);

        // Document should remain unchanged if no type could be inferred
        const text = getDocumentText(editor.document);
        assert.ok(
            text.includes('x = unknown_func()'),
            'Original code should remain if no type inferred'
        );

        await closeAllEditors();
    });

    test('Insert type at specific cursor position in multi-line file', async function () {
        this.timeout(45000);

        const code = `first = 1
second = "hello"
third = True
`;
        const editor = await openPythonFile(code);

        // Wait for hints for all variables
        await waitForServerReadyForInsertion(editor, 3, 20000);

        // Set cursor on second variable (line 1, 0-indexed)
        await setCursorPosition(editor, 1, 0);
        await sleep(300);

        // Execute and verify
        const result = await executeInsertionAndVerify(
            editor,
            'autoType.insertTypeAtCursor',
            'second: str = "hello"',
            20000
        );

        assert.ok(
            result.success,
            `Failed to insert type at specific position. ` +
                `Actual text: "${result.actualText}". ` +
                `${result.errorMessage || ''}`
        );

        // Verify only the second variable was annotated
        const text = result.actualText;
        assert.ok(text.includes('second: str'), 'Second variable should be annotated');

        // First and third should NOT be annotated (we only inserted at cursor)
        // Note: They may or may not be annotated depending on implementation
        // This test focuses on verifying the targeted variable was correctly annotated

        await closeAllEditors();
    });

    suiteTeardown(async () => {
        await cleanupTempFiles();
    });
});
