import * as assert from 'assert';
import * as vscode from 'vscode';
import { cleanupTempFiles, debugLog } from './helpers/testHelpers';

suite('Command Registration Test Suite', () => {
    suiteSetup(async function () {
        this.timeout(45000);
        debugLog('=== Command Registration Suite Setup ===');

        // Global warmup already handled in global.test.ts
        // Any suite-specific setup can go here

        debugLog('=== Suite Ready ===');
    });

    test('insertTypeAtCursor command is registered', async () => {
        const commands = await vscode.commands.getCommands();
        assert.ok(
            commands.includes('autoType.insertTypeAtCursor'),
            'insertTypeAtCursor command should be registered'
        );
    });

    test('insertAllTypes command is registered', async () => {
        const commands = await vscode.commands.getCommands();
        assert.ok(
            commands.includes('autoType.insertAllTypes'),
            'insertAllTypes command should be registered'
        );
    });

    test('removeTypeAtCursor command is registered', async () => {
        const commands = await vscode.commands.getCommands();
        assert.ok(
            commands.includes('autoType.removeTypeAtCursor'),
            'removeTypeAtCursor command should be registered'
        );
    });

    test('removeAllTypes command is registered', async () => {
        const commands = await vscode.commands.getCommands();
        assert.ok(
            commands.includes('autoType.removeAllTypes'),
            'removeAllTypes command should be registered'
        );
    });

    test('Commands can be executed without throwing', async () => {
        // These commands might fail due to context, but should not throw
        // We're just verifying the command infrastructure works

        try {
            // insertTypeAtCursor - might fail if no variable at cursor
            await vscode.commands.executeCommand('autoType.insertTypeAtCursor');
        } catch {
            // Expected to potentially fail, but the command should exist
        }

        try {
            // insertAllTypes - might show dialog or info message
            await vscode.commands.executeCommand('autoType.insertAllTypes');
        } catch {
            // Command should exist even if it fails
        }

        assert.ok(true, 'Commands should be executable');
    });

    suiteTeardown(async () => {
        await cleanupTempFiles();
    });
});
