import * as assert from 'assert';
import {
    openPythonFile,
    closeAllEditors,
    sleep,
    setCursorPosition,
    debugLog,
    cleanupTempFiles,
    executeInsertionAndVerify,
    waitForServerReadyForInsertion,
} from './helpers/testHelpers';
import type { InsertionVerificationResult } from './helpers/testHelpers';

/** Insertion verification: hint inferred, document modified, correct annotation present. */

suite('Insertion Verification Test Suite', () => {
    suiteSetup(async function () {
        this.timeout(45000);

        // Global warmup lives in global.test.ts; suite-specific setup goes here.
    });

    /** Helper to run a single insertion test with full verification. */
    async function verifyInsertion(
        description: string,
        inputCode: string,
        cursorLine: number,
        cursorCol: number,
        expectedPattern: string | RegExp,
        expectedHintCount = 1
    ): Promise<InsertionVerificationResult> {
        debugLog(`=== Test: ${description} ===`);

        const editor = await openPythonFile(inputCode);

        // Wait for server with expected number of hints
        const hints = await waitForServerReadyForInsertion(editor, expectedHintCount, 25000);
        debugLog(`Got ${hints.length} hints for: ${description}`);

        // Set cursor position
        await setCursorPosition(editor, cursorLine, cursorCol);
        await sleep(300);

        // Execute and verify
        const result = await executeInsertionAndVerify(
            editor,
            'fangtype.insertTypeAtCursor',
            expectedPattern,
            20000
        );

        await closeAllEditors();
        return result;
    }

    // ===== BASIC PRIMITIVE TYPES =====

    suite('Primitive Types', () => {
        test('Integer literal', async function () {
            this.timeout(45000);
            const result = await verifyInsertion(
                'integer literal',
                'x = 42\n',
                0,
                0,
                'x: int = 42'
            );
            assert.ok(result.success, result.errorMessage);
        });

        test('Negative integer', async function () {
            this.timeout(45000);
            const result = await verifyInsertion(
                'negative integer',
                'x = -10\n',
                0,
                0,
                'x: int = -10'
            );
            assert.ok(result.success, result.errorMessage);
        });

        test('String with double quotes', async function () {
            this.timeout(45000);
            const result = await verifyInsertion(
                'string double quotes',
                'msg = "hello"\n',
                0,
                0,
                'msg: str = "hello"'
            );
            assert.ok(result.success, result.errorMessage);
        });

        test('String with single quotes', async function () {
            this.timeout(45000);
            const result = await verifyInsertion(
                'string single quotes',
                "msg = 'hello'\n",
                0,
                0,
                /msg:\s*str\s*=\s*'hello'/
            );
            assert.ok(result.success, result.errorMessage);
        });

        test('Empty string', async function () {
            this.timeout(45000);
            const result = await verifyInsertion(
                'empty string',
                'empty = ""\n',
                0,
                0,
                'empty: str = ""'
            );
            assert.ok(result.success, result.errorMessage);
        });

        test('Float with decimal', async function () {
            this.timeout(45000);
            const result = await verifyInsertion(
                'float decimal',
                'pi = 3.14159\n',
                0,
                0,
                'pi: float = 3.14159'
            );
            assert.ok(result.success, result.errorMessage);
        });

        test('Float without leading zero', async function () {
            this.timeout(45000);
            const result = await verifyInsertion(
                'float no leading zero',
                'x = .5\n',
                0,
                0,
                /x:\s*float\s*=\s*\.5/
            );
            assert.ok(result.success, result.errorMessage);
        });

        test('Boolean True', async function () {
            this.timeout(45000);
            const result = await verifyInsertion(
                'boolean True',
                'flag = True\n',
                0,
                0,
                'flag: bool = True'
            );
            assert.ok(result.success, result.errorMessage);
        });

        test('Boolean False', async function () {
            this.timeout(45000);
            const result = await verifyInsertion(
                'boolean False',
                'flag = False\n',
                0,
                0,
                'flag: bool = False'
            );
            assert.ok(result.success, result.errorMessage);
        });

        test('None value', async function () {
            this.timeout(45000);
            const result = await verifyInsertion(
                'None value',
                'nothing = None\n',
                0,
                0,
                /nothing:\s*None\s*=\s*None/
            );
            assert.ok(result.success, result.errorMessage);
        });
    });

    // ===== CONTAINER TYPES =====

    suite('Container Types', () => {
        test('List of integers', async function () {
            this.timeout(45000);
            const result = await verifyInsertion(
                'list of integers',
                'nums = [1, 2, 3]\n',
                0,
                0,
                /nums:\s*list\[int\]\s*=\s*\[1, 2, 3\]/
            );
            assert.ok(result.success, result.errorMessage);
        });

        test('List of strings', async function () {
            this.timeout(45000);
            const result = await verifyInsertion(
                'list of strings',
                'names = ["a", "b", "c"]\n',
                0,
                0,
                /names:\s*list\[str\]\s*=/
            );
            assert.ok(result.success, result.errorMessage);
        });

        test('Empty list', async function () {
            this.timeout(45000);
            const result = await verifyInsertion(
                'empty list',
                'empty = []\n',
                0,
                0,
                /empty:\s*list\s*=\s*\[\]/
            );
            assert.ok(result.success, result.errorMessage);
        });

        test('Dictionary string to int', async function () {
            this.timeout(45000);
            const result = await verifyInsertion(
                'dict str to int',
                'ages = {"alice": 30, "bob": 25}\n',
                0,
                0,
                /ages:\s*dict\[str,\s*int\]\s*=/
            );
            assert.ok(result.success, result.errorMessage);
        });

        test('Dictionary string to string', async function () {
            this.timeout(45000);
            const result = await verifyInsertion(
                'dict str to str',
                'data = {"key": "value"}\n',
                0,
                0,
                /data:\s*dict\[str,\s*str\]\s*=/
            );
            assert.ok(result.success, result.errorMessage);
        });

        test('Empty dictionary', async function () {
            this.timeout(45000);
            const result = await verifyInsertion(
                'empty dict',
                'empty = {}\n',
                0,
                0,
                /empty:\s*dict\s*=\s*\{\}/
            );
            assert.ok(result.success, result.errorMessage);
        });

        test('Set of integers', async function () {
            this.timeout(45000);
            const result = await verifyInsertion(
                'set of integers',
                'unique = {1, 2, 3}\n',
                0,
                0,
                /unique:\s*set\[int\]\s*=/
            );
            assert.ok(result.success, result.errorMessage);
        });

        test('Tuple literal', async function () {
            this.timeout(45000);
            const result = await verifyInsertion(
                'tuple literal',
                'point = (1, 2)\n',
                0,
                0,
                /point:\s*tuple\[int,\s*int\]\s*=/
            );
            assert.ok(result.success, result.errorMessage);
        });
    });

    // ===== MULTI-VARIABLE FILES =====

    suite('Multi-Variable Scenarios', () => {
        test('Insert type for first variable in multi-var file', async function () {
            this.timeout(45000);

            const code = `first = 1
second = 2
third = 3
`;
            const result = await verifyInsertion(
                'first of three',
                code,
                0,
                0,
                'first: int = 1',
                3 // Expect 3 hints
            );
            assert.ok(result.success, result.errorMessage);
        });

        test('Insert type for middle variable', async function () {
            this.timeout(45000);

            const code = `alpha = "a"
beta = "b"
gamma = "c"
`;
            const editor = await openPythonFile(code);

            await waitForServerReadyForInsertion(editor, 3, 25000);

            // Set cursor on middle variable (line 1, 0-indexed)
            await setCursorPosition(editor, 1, 0);
            await sleep(300);

            const result = await executeInsertionAndVerify(
                editor,
                'fangtype.insertTypeAtCursor',
                'beta: str = "b"',
                20000
            );

            assert.ok(result.success, result.errorMessage);
            await closeAllEditors();
        });

        test('Insert type for last variable', async function () {
            this.timeout(45000);

            const code = `one = 1
two = 2
three = 3
`;
            const editor = await openPythonFile(code);

            await waitForServerReadyForInsertion(editor, 3, 25000);

            // Set cursor on last variable (line 2, 0-indexed)
            await setCursorPosition(editor, 2, 0);
            await sleep(300);

            const result = await executeInsertionAndVerify(
                editor,
                'fangtype.insertTypeAtCursor',
                'three: int = 3',
                20000
            );

            assert.ok(result.success, result.errorMessage);
            await closeAllEditors();
        });

        test('Mixed types in same file', async function () {
            this.timeout(45000);

            const code = `count = 10
name = "test"
active = True
ratio = 0.5
`;
            const editor = await openPythonFile(code);

            const hints = await waitForServerReadyForInsertion(editor, 4, 25000);

            // Verify we have hints for all four types
            const hintLabels = hints.map(h =>
                typeof h.label === 'string' ? h.label : (h.label[0]?.value ?? '')
            );

            assert.ok(
                hintLabels.some(l => l.includes('int')),
                'Should have int hint'
            );
            assert.ok(
                hintLabels.some(l => l.includes('str')),
                'Should have str hint'
            );
            assert.ok(
                hintLabels.some(l => l.includes('bool')),
                'Should have bool hint'
            );
            assert.ok(
                hintLabels.some(l => l.includes('float')),
                'Should have float hint'
            );

            // Insert type for first variable
            await setCursorPosition(editor, 0, 0);
            await sleep(300);

            const result = await executeInsertionAndVerify(
                editor,
                'fangtype.insertTypeAtCursor',
                'count: int = 10',
                20000
            );

            assert.ok(result.success, result.errorMessage);
            await closeAllEditors();
        });
    });

    // ===== VARIABLE NAMING =====

    suite('Variable Naming Patterns', () => {
        test('Snake case variable', async function () {
            this.timeout(45000);
            const result = await verifyInsertion(
                'snake_case',
                'my_variable = 42\n',
                0,
                0,
                'my_variable: int = 42'
            );
            assert.ok(result.success, result.errorMessage);
        });

        test('Camel case variable', async function () {
            this.timeout(45000);
            const result = await verifyInsertion(
                'camelCase',
                'myVariable = 42\n',
                0,
                0,
                'myVariable: int = 42'
            );
            assert.ok(result.success, result.errorMessage);
        });

        test('Single letter variable', async function () {
            this.timeout(45000);
            const result = await verifyInsertion('single letter', 'x = 1\n', 0, 0, 'x: int = 1');
            assert.ok(result.success, result.errorMessage);
        });

        test('Underscore prefix (private)', async function () {
            this.timeout(45000);
            const result = await verifyInsertion(
                'underscore prefix',
                '_private = "secret"\n',
                0,
                0,
                '_private: str = "secret"'
            );
            assert.ok(result.success, result.errorMessage);
        });

        test('Double underscore prefix', async function () {
            this.timeout(45000);
            const result = await verifyInsertion(
                'double underscore',
                '__very_private = 123\n',
                0,
                0,
                '__very_private: int = 123'
            );
            assert.ok(result.success, result.errorMessage);
        });

        test('ALL_CAPS constant style', async function () {
            this.timeout(45000);
            const result = await verifyInsertion(
                'ALL_CAPS',
                'MAX_VALUE = 100\n',
                0,
                0,
                'MAX_VALUE: int = 100'
            );
            assert.ok(result.success, result.errorMessage);
        });
    });

    // ===== EXPRESSIONS =====

    suite('Expression-based Assignments', () => {
        test('Binary operation (addition)', async function () {
            this.timeout(45000);
            const result = await verifyInsertion(
                'binary addition',
                'result = 1 + 2\n',
                0,
                0,
                /result:\s*int\s*=\s*1 \+ 2/
            );
            assert.ok(result.success, result.errorMessage);
        });

        test('String concatenation', async function () {
            this.timeout(45000);
            const result = await verifyInsertion(
                'string concat',
                'greeting = "hello" + " world"\n',
                0,
                0,
                /greeting:\s*str\s*=/
            );
            assert.ok(result.success, result.errorMessage);
        });

        test('List multiplication', async function () {
            this.timeout(45000);
            const result = await verifyInsertion(
                'list multiplication',
                'repeated = [0] * 5\n',
                0,
                0,
                /repeated:\s*list\[int\]\s*=/
            );
            assert.ok(result.success, result.errorMessage);
        });

        test('Boolean expression', async function () {
            this.timeout(45000);
            const result = await verifyInsertion(
                'boolean expression',
                'check = True and False\n',
                0,
                0,
                /check:\s*bool\s*=/
            );
            assert.ok(result.success, result.errorMessage);
        });
    });

    suiteTeardown(async () => {
        await cleanupTempFiles();
    });
});
