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
    waitForInlayHints,
    retryOperation,
} from './helpers/testHelpers';

/**
 * Insertion Edge Cases Test Suite
 *
 * Tests for edge cases, error conditions, and complex scenarios
 * that might not work correctly or require special handling.
 */

suite('Insertion Edge Cases Test Suite', () => {
    suiteSetup(async function () {
        this.timeout(45000);

        // Global warmup already handled in global.test.ts
        // Any suite-specific setup can go here
    });

    // ==========================================================================
    // ALREADY ANNOTATED VARIABLES
    // ==========================================================================

    suite('Already Annotated Variables', () => {
        test('Should not duplicate annotation on already-typed variable', async function () {
            this.timeout(30000);

            const editor = await openPythonFile('x: int = 5\n');

            await sleep(1500);

            // Set cursor on x
            await setCursorPosition(editor, 0, 0);
            await sleep(300);

            const originalText = getDocumentText(editor.document);
            void originalText; // Mark as intentionally unused - used for debugging context

            // Execute command
            await vscode.commands.executeCommand('autoType.insertTypeAtCursor');
            await sleep(1000);

            const newText = getDocumentText(editor.document);

            // Should not have "x: int: int" or similar duplication
            assert.ok(!newText.includes('x: int: int'), 'Should not duplicate type annotation');
            assert.ok(
                !newText.includes('x: int : int'),
                'Should not duplicate type annotation with spaces'
            );

            // Original annotation should be preserved
            assert.ok(newText.includes('x: int = 5'), 'Original annotation should be preserved');

            await closeAllEditors();
        });

        test('Should not show hint for already-annotated variable', async function () {
            this.timeout(30000);

            const editor = await openPythonFile('x: int = 5\n');

            await sleep(1500);

            // Get inlay hints - should be 0 for already annotated
            const hints = await waitForInlayHints(editor.document, 0, 5000).catch(() => []); // Expected to have 0 hints

            // Should have no hints since variable is already annotated
            assert.strictEqual(
                hints.length,
                0,
                'Should not show inlay hints for already-annotated variables'
            );

            await closeAllEditors();
        });

        test('Mixed annotated and unannotated variables', async function () {
            this.timeout(45000);

            const code = `annotated: str = "hello"
unannotated = 42
also_annotated: bool = True
`;
            const editor = await openPythonFile(code);

            // Should only have 1 hint (for unannotated)
            const hints = await retryOperation(
                async () => {
                    const h = await waitForInlayHints(editor.document, 1, 10000);
                    return h;
                },
                3,
                1000
            ).catch(() => []);

            assert.strictEqual(
                hints.length,
                1,
                `Expected 1 hint for unannotated variable, got ${hints.length}`
            );

            // Insert type for unannotated variable
            await setCursorPosition(editor, 1, 0);
            await sleep(300);

            const result = await executeInsertionAndVerify(
                editor,
                'autoType.insertTypeAtCursor',
                'unannotated: int = 42',
                15000
            );

            assert.ok(result.success, result.errorMessage);

            // Verify existing annotations are preserved
            const text = result.actualText;
            assert.ok(text.includes('annotated: str = "hello"'), 'First annotation preserved');
            assert.ok(text.includes('also_annotated: bool = True'), 'Third annotation preserved');

            await closeAllEditors();
        });
    });

    // ==========================================================================
    // COMMENTS AND STRINGS
    // ==========================================================================

    suite('Comments and Strings', () => {
        test('Variable in comment should not be annotated', async function () {
            this.timeout(30000);

            const code = `# x = 5 <- this is a comment
real_var = 10
`;
            const editor = await openPythonFile(code);

            // Should only have hint for real_var
            await waitForServerReadyForInsertion(editor, 1, 15000);

            // Set cursor on comment line
            await setCursorPosition(editor, 0, 2);
            await vscode.commands.executeCommand('autoType.insertTypeAtCursor');
            await sleep(500);

            const text = getDocumentText(editor.document);
            assert.ok(text.includes('# x = 5'), 'Comment should not be modified');

            await closeAllEditors();
        });

        test('Variable name in string should not affect real variable', async function () {
            this.timeout(45000);

            const code = `message = "x = 5"
x = 42
`;
            const editor = await openPythonFile(code);

            await waitForServerReadyForInsertion(editor, 2, 15000);

            // Insert type for x (line 1)
            await setCursorPosition(editor, 1, 0);
            await sleep(300);

            const result = await executeInsertionAndVerify(
                editor,
                'autoType.insertTypeAtCursor',
                'x: int = 42',
                15000
            );

            assert.ok(result.success, result.errorMessage);

            // String should not be modified
            assert.ok(
                result.actualText.includes('message = "x = 5"') ||
                    result.actualText.includes('message: str = "x = 5"'),
                'String content should not be affected by insertion'
            );

            await closeAllEditors();
        });

        test('Multi-line string assignment', async function () {
            this.timeout(45000);

            const code = `text = """
This is a
multi-line string
"""
`;
            const editor = await openPythonFile(code);

            await waitForServerReadyForInsertion(editor, 1, 15000);

            await setCursorPosition(editor, 0, 0);
            await sleep(300);

            const result = await executeInsertionAndVerify(
                editor,
                'autoType.insertTypeAtCursor',
                /text:\s*str\s*=/,
                15000
            );

            assert.ok(result.success, result.errorMessage);

            await closeAllEditors();
        });
    });

    // ==========================================================================
    // SPECIAL ASSIGNMENTS
    // ==========================================================================

    suite('Special Assignment Patterns', () => {
        test('Augmented assignment should not get type hint', async function () {
            this.timeout(30000);

            const code = `x = 0
x += 1
`;
            const editor = await openPythonFile(code);

            // Should only have hint for first assignment
            const hints = await waitForServerReadyForInsertion(editor, 1, 15000);
            assert.strictEqual(hints.length, 1, 'Should only hint first assignment');

            await closeAllEditors();
        });

        test('Walrus operator assignment', async function () {
            this.timeout(45000);

            // Skip if Python version doesn't support walrus operator
            const code = `if (n := 10) > 5:
    print(n)
`;
            const editor = await openPythonFile(code);

            await sleep(2000);

            // Walrus operator might or might not get hints depending on implementation
            // Just verify no crash
            const text = getDocumentText(editor.document);
            assert.ok(text.includes('n := 10'), 'Code should be valid');

            await closeAllEditors();
        });

        test('Chained comparison assignment', async function () {
            this.timeout(45000);

            const code = `result = 1 < 2 < 3
`;
            const editor = await openPythonFile(code);

            await waitForServerReadyForInsertion(editor, 1, 15000);

            await setCursorPosition(editor, 0, 0);
            await sleep(300);

            const result = await executeInsertionAndVerify(
                editor,
                'autoType.insertTypeAtCursor',
                /result:\s*bool\s*=/,
                15000
            );

            assert.ok(result.success, result.errorMessage);

            await closeAllEditors();
        });
    });

    // ==========================================================================
    // COMPLEX TYPES
    // ==========================================================================

    suite('Complex Type Patterns', () => {
        test('Nested list', async function () {
            this.timeout(45000);

            const code = `matrix = [[1, 2], [3, 4]]
`;
            const editor = await openPythonFile(code);

            await waitForServerReadyForInsertion(editor, 1, 15000);

            await setCursorPosition(editor, 0, 0);
            await sleep(300);

            const result = await executeInsertionAndVerify(
                editor,
                'autoType.insertTypeAtCursor',
                /matrix:\s*list\[list\[int\]\]\s*=/,
                15000
            );

            assert.ok(result.success, result.errorMessage);

            await closeAllEditors();
        });

        test('Dict of lists', async function () {
            this.timeout(45000);

            const code = `groups = {"a": [1, 2], "b": [3, 4]}
`;
            const editor = await openPythonFile(code);

            await waitForServerReadyForInsertion(editor, 1, 15000);

            await setCursorPosition(editor, 0, 0);
            await sleep(300);

            const result = await executeInsertionAndVerify(
                editor,
                'autoType.insertTypeAtCursor',
                /groups:\s*dict\[str,\s*list\[int\]\]\s*=/,
                15000
            );

            assert.ok(result.success, result.errorMessage);

            await closeAllEditors();
        });

        test('List of tuples', async function () {
            this.timeout(45000);

            const code = `points = [(1, 2), (3, 4)]
`;
            const editor = await openPythonFile(code);

            await waitForServerReadyForInsertion(editor, 1, 15000);

            await setCursorPosition(editor, 0, 0);
            await sleep(300);

            const result = await executeInsertionAndVerify(
                editor,
                'autoType.insertTypeAtCursor',
                /points:\s*list\[tuple\[int,\s*int\]\]\s*=/,
                15000
            );

            assert.ok(result.success, result.errorMessage);

            await closeAllEditors();
        });
    });

    // ==========================================================================
    // ERROR CASES
    // ==========================================================================

    suite('Error Handling', () => {
        test('Unknown function call should not crash', async function () {
            this.timeout(30000);

            const code = `result = unknown_function()
`;
            const editor = await openPythonFile(code);

            await sleep(2000);

            // Set cursor and try to insert
            await setCursorPosition(editor, 0, 0);
            await vscode.commands.executeCommand('autoType.insertTypeAtCursor');
            await sleep(500);

            // Should not crash - code may or may not change
            const text = getDocumentText(editor.document);
            assert.ok(text.includes('unknown_function'), 'Code should still be valid');

            await closeAllEditors();
        });

        test('Syntax error in file should be handled gracefully', async function () {
            this.timeout(30000);

            // File with syntax error
            const code = `x = 5
y = (incomplete
`;
            const editor = await openPythonFile(code);

            await sleep(1500);

            // Try to execute command - should not crash
            await setCursorPosition(editor, 0, 0);
            await vscode.commands.executeCommand('autoType.insertTypeAtCursor');
            await sleep(500);

            // Should not crash
            const text = getDocumentText(editor.document);
            assert.ok(text.includes('x = 5'), 'First line should be preserved');

            await closeAllEditors();
        });

        test('Empty file should be handled gracefully', async function () {
            this.timeout(30000);

            const editor = await openPythonFile('');

            await sleep(1000);

            // Try to execute command on empty file
            await vscode.commands.executeCommand('autoType.insertTypeAtCursor');
            await sleep(500);

            // Should not crash
            const text = getDocumentText(editor.document);
            assert.strictEqual(text, '', 'Empty file should remain empty');

            await closeAllEditors();
        });

        test('File with only comments should be handled gracefully', async function () {
            this.timeout(30000);

            const code = `# This is a comment
# Another comment
# x = 5 would be here
`;
            const editor = await openPythonFile(code);

            await sleep(1000);

            // Try to execute command
            await setCursorPosition(editor, 0, 0);
            await vscode.commands.executeCommand('autoType.insertTypeAtCursor');
            await sleep(500);

            // Should not crash or modify
            const text = getDocumentText(editor.document);
            assert.ok(text.includes('# This is a comment'), 'Comments should be preserved');

            await closeAllEditors();
        });
    });

    // ==========================================================================
    // INDENTATION AND FORMATTING
    // ==========================================================================

    suite('Indentation and Formatting', () => {
        test('Variable inside function body', async function () {
            this.timeout(45000);

            const code = `def foo():
    x = 42
    return x
`;
            const editor = await openPythonFile(code);

            await waitForServerReadyForInsertion(editor, 1, 15000);

            // Set cursor on x inside function (line 1, with indentation)
            await setCursorPosition(editor, 1, 4);
            await sleep(300);

            const result = await executeInsertionAndVerify(
                editor,
                'autoType.insertTypeAtCursor',
                /    x:\s*int\s*=\s*42/, // Should preserve indentation
                15000
            );

            assert.ok(result.success, result.errorMessage);

            await closeAllEditors();
        });

        test('Variable inside class method', async function () {
            this.timeout(45000);

            const code = `class MyClass:
    def method(self):
        value = "test"
        return value
`;
            const editor = await openPythonFile(code);

            await waitForServerReadyForInsertion(editor, 1, 15000);

            // Set cursor on value inside method (line 2)
            await setCursorPosition(editor, 2, 8);
            await sleep(300);

            const result = await executeInsertionAndVerify(
                editor,
                'autoType.insertTypeAtCursor',
                /        value:\s*str\s*=\s*"test"/, // Should preserve 8-space indent
                15000
            );

            assert.ok(result.success, result.errorMessage);

            await closeAllEditors();
        });

        test('Tab-indented code', async function () {
            this.timeout(45000);

            const code = 'def foo():\n\tx = 42\n\treturn x\n';
            const editor = await openPythonFile(code);

            await waitForServerReadyForInsertion(editor, 1, 15000);

            // Set cursor on x (line 1, after tab)
            await setCursorPosition(editor, 1, 1);
            await sleep(300);

            const result = await executeInsertionAndVerify(
                editor,
                'autoType.insertTypeAtCursor',
                /\tx:\s*int\s*=\s*42/, // Should preserve tab
                15000
            );

            assert.ok(result.success, result.errorMessage);

            await closeAllEditors();
        });
    });

    // ==========================================================================
    // FUNCTION PARAMETERS AND RETURNS
    // ==========================================================================

    suite('Function Signatures', () => {
        test('Function with simple parameter types', async function () {
            this.timeout(45000);

            const code = `def greet(name, age):
    return f"Hello {name}, you are {age}"
`;
            const editor = await openPythonFile(code);

            await sleep(2000);

            // Get hints - may include function signature hints
            const hints = await waitForInlayHints(editor.document, 0, 5000).catch(() => []);

            debugLog(`Got ${hints.length} hints for function`);

            // Verify code is valid
            const text = getDocumentText(editor.document);
            assert.ok(text.includes('def greet'), 'Function should be present');

            await closeAllEditors();
        });

        test('Function with return statement', async function () {
            this.timeout(45000);

            const code = `def add(a, b):
    return a + b

result = add(1, 2)
`;
            const editor = await openPythonFile(code);

            await sleep(2000);

            // Should have hint for result variable at least
            await waitForServerReadyForInsertion(editor, 1, 15000);

            // Insert type for result
            await setCursorPosition(editor, 3, 0);
            await sleep(300);

            const result = await executeInsertionAndVerify(
                editor,
                'autoType.insertTypeAtCursor',
                /result:\s*int\s*=/,
                15000
            );

            assert.ok(result.success, result.errorMessage);

            await closeAllEditors();
        });
    });

    suiteTeardown(async () => {
        await cleanupTempFiles();
    });
});
