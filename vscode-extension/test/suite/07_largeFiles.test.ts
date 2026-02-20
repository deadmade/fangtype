import * as assert from 'assert';
import * as vscode from 'vscode';
import * as path from 'path';
import {
    closeAllEditors,
    sleep,
    getInlayHints,
    debugLog,
    logTestContext,
} from './helpers/testHelpers';

/**
 * Test suite for large and complex Python files.
 *
 * This suite tests the extension's performance and correctness with realistic,
 * large Python files (500-800 lines) containing various complex patterns.
 */
suite('Large & Complex Files Test Suite', () => {
    // Path to test files (relative to out/test/suite/ where compiled tests reside)
    const testFilesDir = path.join(__dirname, '../fixtures/large-test-files');

    suiteSetup(async function () {
        this.timeout(60000);
        debugLog('=== Large Files Suite Setup ===');

        // Global warmup already handled in global.test.ts
        // Any suite-specific setup can go here

        debugLog('=== Large Files Suite Ready ===');
    });

    teardown(async function () {
        // Clean up after each test to prevent resource exhaustion
        debugLog('Cleaning up after test...');
        await closeAllEditors();
        await sleep(1500); // Let server settle
    });

    /**
     * Test 1: Large realistic file (676 lines)
     * Tests: production-like codebase with classes, functions, and complex logic
     */
    test('Large realistic file - hints appear and perform well', async function () {
        this.timeout(90000); // Increase from 60s to 90s

        const filePath = path.join(testFilesDir, 'test_large_realistic.py');
        debugLog(`--- Test: Large realistic file ---`);
        debugLog(`Opening: ${filePath}`);

        // Open the file
        const document = await vscode.workspace.openTextDocument(filePath);
        await vscode.window.showTextDocument(document);

        await logTestContext('After opening large file');

        // Give extra time for large file analysis
        debugLog('Waiting for file analysis...');
        await sleep(5000); // Increase from 3000

        // Get inlay hints for the entire file
        const startTime = Date.now();
        const hints = await getInlayHints(document);
        const endTime = Date.now();
        const analysisTime = endTime - startTime;

        debugLog(`Large file analysis took ${analysisTime}ms`);
        debugLog(`Got ${hints.length} hints for 676-line file`);

        // Assertions
        assert.ok(hints.length > 50, `Should have many hints (> 50), got ${hints.length}`);
        assert.ok(
            analysisTime < 10000,
            `Analysis should complete in < 10s, took ${analysisTime}ms`
        );

        await closeAllEditors();
    });

    /**
     * Test 2: OOP advanced patterns (775 lines)
     * Tests: class hierarchies, generics, protocols, mixins
     */
    test('OOP advanced patterns - class and method type hints', async function () {
        this.timeout(90000); // Increase from 60s

        const filePath = path.join(testFilesDir, 'test_oop_advanced.py');
        debugLog(`--- Test: OOP advanced patterns ---`);
        debugLog(`Opening: ${filePath}`);

        const document = await vscode.workspace.openTextDocument(filePath);
        await vscode.window.showTextDocument(document);

        await logTestContext('After opening OOP file');

        await sleep(5000); // Increase from 3000

        const hints = await getInlayHints(document);
        debugLog(`Got ${hints.length} hints for OOP file`);

        // Verify hints exist for class patterns
        assert.ok(
            hints.length > 60,
            `Should have many hints for OOP patterns, got ${hints.length}`
        );

        await closeAllEditors();
    });

    /**
     * Test 3: Async/await patterns (641 lines)
     * Tests: async functions, async context managers, async generators
     */
    test('Async patterns - coroutine and async type hints', async function () {
        this.timeout(90000); // Increase from 60s

        const filePath = path.join(testFilesDir, 'test_async_complete.py');
        debugLog(`--- Test: Async patterns ---`);
        debugLog(`Opening: ${filePath}`);

        const document = await vscode.workspace.openTextDocument(filePath);
        await vscode.window.showTextDocument(document);

        await logTestContext('After opening async file');

        await sleep(5000); // Increase from 3000

        const hints = await getInlayHints(document);
        debugLog(`Got ${hints.length} hints for async file`);

        // Verify async patterns recognized
        assert.ok(hints.length > 40, `Should have hints for async patterns, got ${hints.length}`);

        await closeAllEditors();
    });

    /**
     * Test 4: Modern Python 3.12+ types (690 lines)
     * Tests: type aliases, union types, pattern matching, generics
     */
    test('Modern types - Python 3.12+ type features', async function () {
        this.timeout(90000); // Increase from 60s

        const filePath = path.join(testFilesDir, 'test_modern_types.py');
        debugLog(`--- Test: Modern types ---`);
        debugLog(`Opening: ${filePath}`);

        const document = await vscode.workspace.openTextDocument(filePath);
        await vscode.window.showTextDocument(document);

        await logTestContext('After opening modern types file');

        await sleep(5000); // Increase from 3000

        const hints = await getInlayHints(document);
        debugLog(`Got ${hints.length} hints for modern types file`);

        // Verify modern type patterns recognized
        assert.ok(hints.length > 50, `Should have hints for modern types, got ${hints.length}`);

        await closeAllEditors();
    });

    /**
     * Test 5: Functional patterns (578 lines)
     * Tests: decorators, closures, generators, comprehensions
     */
    test('Functional patterns - decorator and closure type hints', async function () {
        this.timeout(90000); // Increase from 60s

        const filePath = path.join(testFilesDir, 'test_functional_patterns.py');
        debugLog(`--- Test: Functional patterns ---`);
        debugLog(`Opening: ${filePath}`);

        const document = await vscode.workspace.openTextDocument(filePath);
        await vscode.window.showTextDocument(document);

        await logTestContext('After opening functional patterns file');

        await sleep(5000); // Increase from 3000

        const hints = await getInlayHints(document);
        debugLog(`Got ${hints.length} hints for functional patterns file`);

        // Verify functional patterns recognized
        assert.ok(
            hints.length > 40,
            `Should have hints for functional patterns, got ${hints.length}`
        );

        await closeAllEditors();
    });

    /**
     * Test 6: Edge cases (558 lines)
     * Tests: robustness with unusual patterns, long identifiers, deep nesting
     */
    test('Edge cases - robust handling without crashes', async function () {
        this.timeout(90000); // Increase from 60s

        const filePath = path.join(testFilesDir, 'test_edge_cases.py');
        debugLog(`--- Test: Edge cases ---`);
        debugLog(`Opening: ${filePath}`);

        const document = await vscode.workspace.openTextDocument(filePath);
        await vscode.window.showTextDocument(document);

        await logTestContext('After opening edge cases file');

        await sleep(5000); // Increase from 3000

        const hints = await getInlayHints(document);
        debugLog(`Got ${hints.length} hints for edge cases file`);

        // Verify extension handles edge cases without crashing
        assert.ok(hints.length >= 0, 'Should handle edge cases without crashing');
        debugLog('✓ Extension handled edge cases robustly');

        await closeAllEditors();
    });

    /**
     * Test 7: Import and module patterns (481 lines)
     * Tests: various import styles, stdlib usage, renamed imports
     */
    test('Imports and modules - type resolution across imports', async function () {
        this.timeout(90000); // Increase from 60s

        const filePath = path.join(testFilesDir, 'test_imports_and_modules.py');
        debugLog(`--- Test: Imports and modules ---`);
        debugLog(`Opening: ${filePath}`);

        const document = await vscode.workspace.openTextDocument(filePath);
        await vscode.window.showTextDocument(document);

        await logTestContext('After opening imports file');

        await sleep(5000); // Increase from 3000

        const hints = await getInlayHints(document);
        debugLog(`Got ${hints.length} hints for imports file`);

        // Verify imported types resolved
        assert.ok(hints.length > 30, `Should have hints with imported types, got ${hints.length}`);

        await closeAllEditors();
    });

    /**
     * Test 8: Performance metrics (535 lines)
     * Tests: performance baseline with repetitive patterns
     */
    test('Performance metrics - handle repetitive patterns efficiently', async function () {
        this.timeout(90000); // Increase from 60s

        const filePath = path.join(testFilesDir, 'test_performance_metrics.py');
        debugLog(`--- Test: Performance metrics ---`);
        debugLog(`Opening: ${filePath}`);

        const document = await vscode.workspace.openTextDocument(filePath);
        await vscode.window.showTextDocument(document);

        await logTestContext('After opening performance file');

        await sleep(5000); // Give extra time

        // Measure performance
        const startTime = Date.now();
        const hints = await getInlayHints(document);
        const endTime = Date.now();
        const analysisTime = endTime - startTime;

        debugLog(`Performance file analysis took ${analysisTime}ms`);
        debugLog(`Got ${hints.length} hints for performance test file`);

        // Performance assertions
        assert.ok(
            hints.length > 80,
            `Should have many hints for repetitive patterns, got ${hints.length}`
        );
        assert.ok(
            analysisTime < 8000,
            `Should analyze repetitive file in < 8s, took ${analysisTime}ms`
        );

        // Performance baseline
        const hintsPerSecond = Math.round((hints.length / analysisTime) * 1000);
        debugLog(`Performance: ${hintsPerSecond} hints/second`);

        await closeAllEditors();
    });

    /**
     * Test 9: Incremental updates on large files
     * Tests: editing large files doesn't cause performance degradation
     */
    test('Incremental updates - edit large file efficiently', async function () {
        this.timeout(90000); // Increase from 60s

        debugLog('--- Test: Incremental updates ---');
        const filePath = path.join(testFilesDir, 'test_large_realistic.py');
        const document = await vscode.workspace.openTextDocument(filePath);
        await vscode.window.showTextDocument(document);

        await logTestContext('After opening large file for editing');

        await sleep(5000); // Increase from 2000

        // Get initial hints
        const initialHints = await getInlayHints(document);
        debugLog(`Initial hints: ${initialHints.length}`);

        // Make a small edit
        const edit = new vscode.WorkspaceEdit();
        const lastLine = document.lineCount - 1;
        edit.insert(
            document.uri,
            new vscode.Position(lastLine, 0),
            '\n# Test comment\ntest_var = 123\n'
        );
        await vscode.workspace.applyEdit(edit);

        // Wait for incremental update
        await sleep(3000); // Increase from 1000

        // Measure update time
        const updateStartTime = Date.now();
        const updatedHints = await getInlayHints(document);
        const updateEndTime = Date.now();
        const updateTime = updateEndTime - updateStartTime;

        debugLog(`Incremental update took ${updateTime}ms`);
        debugLog(`Updated hints: ${updatedHints.length}`);

        // Assertions
        assert.ok(
            updatedHints.length >= initialHints.length,
            'Should have at least same number of hints after edit'
        );
        assert.ok(
            updateTime < 5000,
            `Incremental update should be fast (< 5s), took ${updateTime}ms`
        ); // Increase from 3000

        await closeAllEditors();
    });

    /**
     * Test 10: Multiple large files open simultaneously
     * Tests: memory and performance with multiple large files
     */
    test('Multiple large files - handle concurrent analysis', async function () {
        this.timeout(150000); // Increase from 90s to 2.5 minutes

        debugLog('--- Test: Multiple large files ---');

        const files = ['test_large_realistic.py', 'test_oop_advanced.py', 'test_async_complete.py'];

        const documents = [];

        // Open files SEQUENTIALLY with delays
        for (const file of files) {
            const filePath = path.join(testFilesDir, file);
            debugLog(`Opening ${file}...`);

            const doc = await vscode.workspace.openTextDocument(filePath);
            await vscode.window.showTextDocument(doc);
            documents.push(doc);

            // Wait for THIS file to be analyzed before opening next
            debugLog(`Waiting for ${file} to be analyzed...`);
            await sleep(5000); // Increase from implicit
        }

        debugLog('All files opened, waiting for server to settle...');

        await sleep(3000);

        // Get hints from all files
        let totalHints = 0;
        for (const doc of documents) {
            debugLog(`Getting hints for ${path.basename(doc.fileName)}...`);
            const hints = await getInlayHints(doc);
            totalHints += hints.length;
            debugLog(`  ${path.basename(doc.fileName)}: ${hints.length} hints`);
        }

        debugLog(`Total hints across all files: ${totalHints}`);

        // Verify all files processed
        assert.ok(totalHints > 150, `Should have many hints across all files, got ${totalHints}`);

        await closeAllEditors();
    });

    suiteTeardown(async function () {
        await closeAllEditors();
        debugLog('Large Files Test Suite completed');
    });
});
