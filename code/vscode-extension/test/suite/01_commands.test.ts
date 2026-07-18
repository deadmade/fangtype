import * as assert from 'assert';
import * as vscode from 'vscode';
import { cleanupTempFiles, debugLog } from './helpers/testHelpers';

suite('Command Registration Test Suite', () => {
    suiteSetup(async function () {
        this.timeout(45000);
        debugLog('=== Command Registration Suite Setup ===');

        // Global warmup lives in global.test.ts; suite-specific setup goes here.

        debugLog('=== Suite Ready ===');
    });

    test('insertTypeAtCursor command is registered', async () => {
        const commands = await vscode.commands.getCommands();
        assert.ok(
            commands.includes('fangtype.insertTypeAtCursor'),
            'insertTypeAtCursor command should be registered'
        );
    });

    test('insertAllTypes command is registered', async () => {
        const commands = await vscode.commands.getCommands();
        assert.ok(
            commands.includes('fangtype.insertAllTypes'),
            'insertAllTypes command should be registered'
        );
    });

    test('removeTypeAtCursor command is registered', async () => {
        const commands = await vscode.commands.getCommands();
        assert.ok(
            commands.includes('fangtype.removeTypeAtCursor'),
            'removeTypeAtCursor command should be registered'
        );
    });

    test('removeAllTypes command is registered', async () => {
        const commands = await vscode.commands.getCommands();
        assert.ok(
            commands.includes('fangtype.removeAllTypes'),
            'removeAllTypes command should be registered'
        );
    });

    suiteTeardown(async () => {
        await cleanupTempFiles();
    });
});
