import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import {
    closeAllEditors,
    cleanWorkspace,
    openPythonFile,
    setupWorkspace,
} from './helpers/testHelpers';
import type { LanguageClient } from 'vscode-languageclient/node';

/**
 * Global test setup - runs once before all test suites
 * This file provides comprehensive extension activation polling with stage-by-stage progress tracking.
 */

// Track if warmup has completed
let warmupCompleted = false;

/**
 * Log diagnostic information about the extension's dist/ directory.
 * Runs in the test process so output is always visible.
 */
function logExtensionDiagnostics(): void {
    const extension = getExtension();
    if (!extension) {
        console.log('[Warmup:Diag] Extension not found, skipping diagnostics');
        return;
    }

    const extPath = extension.extensionPath;
    console.log(`[Warmup:Diag] Extension path: ${extPath}`);

    const distDir = path.join(extPath, 'dist');
    if (!fs.existsSync(distDir)) {
        console.log('[Warmup:Diag] WARNING: dist/ directory does not exist!');
        return;
    }

    const distContents = fs.readdirSync(distDir);
    console.log(`[Warmup:Diag] dist/ contents: [${distContents.join(', ')}]`);

    // Check extension.cjs
    const extensionCjs = path.join(distDir, 'extension.cjs');
    if (fs.existsSync(extensionCjs)) {
        const stats = fs.statSync(extensionCjs);
        console.log(`[Warmup:Diag] extension.cjs: ${stats.size} bytes`);
    } else {
        console.log('[Warmup:Diag] WARNING: extension.cjs NOT FOUND in dist/');
    }

    // Check server binary
    const serverBinary = path.join(distDir, 'auto-type-server');
    if (fs.existsSync(serverBinary)) {
        const stats = fs.statSync(serverBinary);
        console.log(
            `[Warmup:Diag] auto-type-server: ${stats.size} bytes, mode=${stats.mode.toString(8)}`
        );
    } else {
        console.log('[Warmup:Diag] WARNING: auto-type-server NOT FOUND in dist/');
    }

    // Log package.json main field
    console.log(`[Warmup:Diag] package.json main: ${extension.packageJSON?.main ?? '<missing>'}`);
}

/**
 * Log diagnostic information after extension activation.
 */
function logPostActivationDiagnostics(): void {
    const extension = getExtension();
    if (!extension) {
        return;
    }

    console.log(`[Warmup:Diag] extension.isActive: ${extension.isActive}`);
    console.log(`[Warmup:Diag] extension.exports type: ${typeof extension.exports}`);

    if (extension.exports && typeof extension.exports === 'object') {
        console.log(
            `[Warmup:Diag] extension.exports keys: [${Object.keys(extension.exports).join(', ')}]`
        );
    }
}

/**
 * Activation stage definition
 */
interface ActivationStage {
    name: string;
    check: () => Promise<boolean>;
    timeoutMs: number;
}

/**
 * Sleep utility with adaptive delay
 */
function sleep(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Get extension instance
 */
function getExtension(): vscode.Extension<unknown> | undefined {
    return vscode.extensions.getExtension('auto-type.auto-type');
}

/**
 * Check if extension is present
 */
async function checkExtensionPresent(): Promise<boolean> {
    const extension = getExtension();
    if (!extension) {
        return false;
    }
    console.log(`[Warmup] Extension found at: ${extension.extensionPath}`);
    return true;
}

/**
 * Check if extension is active
 */
async function checkExtensionActive(): Promise<boolean> {
    const extension = getExtension();
    if (!extension) {
        return false;
    }

    if (extension.isActive) {
        console.log(`[Warmup] Extension is active`);
        return true;
    }

    return false;
}

/**
 * Check if all required commands are registered
 */
async function checkCommandsRegistered(): Promise<boolean> {
    const commands = await vscode.commands.getCommands();
    const requiredCommands = [
        'autoType.insertTypeAtCursor',
        'autoType.insertAllTypes',
        'autoType.removeTypeAtCursor',
        'autoType.removeAllTypes',
    ];

    const foundCommands = requiredCommands.filter(cmd => commands.includes(cmd));
    const allRegistered = foundCommands.length === requiredCommands.length;

    if (allRegistered) {
        console.log(`[Warmup] All ${requiredCommands.length} commands registered`);
    } else {
        // Log partial matches for debugging
        const autoTypeCommands = commands.filter(cmd => cmd.startsWith('autoType.'));
        console.log(
            `[Warmup:Diag] Commands found: ${foundCommands.length}/${requiredCommands.length}. ` +
                `autoType.* commands in registry: [${autoTypeCommands.join(', ')}]`
        );
    }

    return allRegistered;
}

/**
 * Check if LSP server is running by inspecting the language client state.
 * This avoids triggering heavy operations like inlay hints during warmup.
 */
async function checkServerResponding(): Promise<boolean> {
    const extension = getExtension();
    if (!extension?.isActive) {
        return false;
    }

    // Access the exported getClient function
    const exports = extension.exports as
        | { getClient?: () => LanguageClient | undefined }
        | undefined;
    if (!exports?.getClient) {
        console.log(
            '[Warmup:Diag] getClient not found on extension exports, falling back to isActive check'
        );
        // Fall back: if the extension is active and commands are registered,
        // the server must be running (commands are registered after server start)
        return true;
    }

    const client = exports.getClient();
    if (!client) {
        return false;
    }

    const isRunning = client.isRunning();
    if (isRunning) {
        console.log(`[Warmup] LSP client is running (state: ${client.state})`);
    }
    return isRunning;
}

/**
 * Check if output channel is ready (extension active implies output channel exists)
 */
async function checkOutputChannelReady(): Promise<boolean> {
    const extension = getExtension();
    if (!extension?.isActive) {
        return false;
    }

    console.log(`[Warmup] Output channel ready`);
    return true;
}

/**
 * Poll through activation stages until all are complete
 */
async function pollUntilReady(stages: ActivationStage[], totalTimeoutMs: number): Promise<void> {
    const startTime = Date.now();
    let currentStageIndex = 0;
    let lastProgressLog = 0;
    let pythonFileOpened = false;

    console.log(
        `[Warmup] Starting activation polling with ${stages.length} stages, total timeout: ${totalTimeoutMs}ms`
    );

    while (currentStageIndex < stages.length) {
        const currentStage = stages[currentStageIndex];

        if (!currentStage) {
            throw new Error(`Invalid stage index: ${currentStageIndex}`);
        }

        const elapsed = Date.now() - startTime;
        const remaining = totalTimeoutMs - elapsed;

        if (remaining <= 0) {
            throw new Error(
                `Timeout: Failed at stage "${currentStage.name}" after ${elapsed}ms. ` +
                    `Completed ${currentStageIndex}/${stages.length} stages.`
            );
        }

        // Adaptive polling: start at 100ms, increase to 1000ms max
        const pollInterval = Math.min(100 + Math.floor(elapsed / 1000) * 100, 1000);

        // Log progress every 3 seconds
        if (elapsed - lastProgressLog >= 3000) {
            const percentComplete = Math.round((currentStageIndex / stages.length) * 100);
            console.log(
                `[Warmup] Progress: ${percentComplete}% (${currentStageIndex}/${stages.length} stages) - ` +
                    `Current: ${currentStage.name} (${elapsed}ms elapsed)`
            );
            lastProgressLog = elapsed;
        }

        // Open Python file to trigger extension activation if needed
        // Do this once before checking extension active stage
        if (!pythonFileOpened && currentStage.name === 'Extension active') {
            console.log('[Warmup] Opening Python file to trigger activation...');
            await openPythonFile('warmup_var = 42\n');
            pythonFileOpened = true;
            // Give it a moment to start activating
            await sleep(200);
        }

        try {
            const stageStartTime = Date.now();
            const isReady = await Promise.race([
                currentStage.check(),
                new Promise<boolean>((_, reject) =>
                    setTimeout(
                        () =>
                            reject(
                                new Error(`Stage check timeout after ${currentStage.timeoutMs}ms`)
                            ),
                        Math.min(currentStage.timeoutMs, remaining)
                    )
                ),
            ]);

            const stageElapsed = Date.now() - stageStartTime;

            if (isReady) {
                console.log(
                    `[Warmup] ✓ Stage ${currentStageIndex + 1}/${stages.length}: ${currentStage.name} ` +
                        `(${stageElapsed}ms, total: ${Date.now() - startTime}ms)`
                );

                // Log post-activation diagnostics after the extension becomes active
                if (currentStage.name === 'Extension active') {
                    logPostActivationDiagnostics();
                }

                currentStageIndex++;
            } else {
                await sleep(pollInterval);
            }
        } catch (error) {
            throw new Error(
                `Stage "${currentStage.name}" failed: ${error}. ` +
                    `Completed ${currentStageIndex}/${stages.length} stages.`
            );
        }
    }

    const totalElapsed = Date.now() - startTime;
    console.log(`[Warmup] ✓ All ${stages.length} stages completed in ${totalElapsed}ms`);
}

/**
 * Perform global warmup with comprehensive stage polling
 */
async function performGlobalWarmup(): Promise<void> {
    if (warmupCompleted) {
        console.log('[Warmup] Already completed, skipping...');
        return;
    }

    console.log('[Warmup] Starting global warmup...');

    // Setup and clean workspace before starting
    await setupWorkspace();
    await cleanWorkspace();
    console.log('[Warmup] Workspace setup and cleaned');

    // Log diagnostic info about the extension before activation
    logExtensionDiagnostics();

    // Define activation stages
    const stages: ActivationStage[] = [
        { name: 'Extension present', check: checkExtensionPresent, timeoutMs: 5000 },
        { name: 'Extension active', check: checkExtensionActive, timeoutMs: 20000 },
        { name: 'Commands registered', check: checkCommandsRegistered, timeoutMs: 10000 },
        { name: 'LSP server responding', check: checkServerResponding, timeoutMs: 25000 },
        { name: 'Output channel ready', check: checkOutputChannelReady, timeoutMs: 5000 },
    ];

    // Poll through all stages
    await pollUntilReady(stages, 60000);

    // Wait for stabilization
    console.log('[Warmup] Waiting for stabilization...');
    await sleep(1000);

    warmupCompleted = true;
    console.log('[Warmup] ✓ Warmup complete');
}

// Global setup - runs once before all test suites
setup(async function () {
    this.timeout(60000);
    await performGlobalWarmup();
});

// Global teardown - runs once after all test suites
teardown(async () => {
    await closeAllEditors();
});
