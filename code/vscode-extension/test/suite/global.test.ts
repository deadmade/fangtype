import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import {
    cleanupTempFiles,
    closeAllEditors,
    cleanWorkspace,
    getInlayHints,
    openPythonFile,
    setupWorkspace,
} from './helpers/testHelpers';
import type { LanguageClient } from 'vscode-languageclient/node';

/** Global setup run once before all suites: polls extension activation stage by stage. */

// Track if warmup has completed
let warmupCompleted = false;

/** Log dist//bundled/ layout and assert the from-source server bootstrap is present. */
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

    // No PyInstaller binary anymore: the server runs from source, so the bootstrap must exist.
    const serverScript = path.join(extPath, 'bundled', 'tool', 'lsp_server.py');
    if (!fs.existsSync(serverScript)) {
        throw new Error(`Server bootstrap not found at: ${serverScript}`);
    }
    console.log(`[Warmup:Diag] server bootstrap: ${serverScript}`);
    console.log(
        `[Warmup:Diag] resolved interpreter: ${process.env.FANGTYPE_INTERPRETER ?? '<unset>'}`
    );

    // Log package.json main field
    console.log(`[Warmup:Diag] package.json main: ${extension.packageJSON?.main ?? '<missing>'}`);
}

/** Log diagnostic information after extension activation. */
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

/** Activation stage definition. */
interface ActivationStage {
    name: string;
    check: () => Promise<boolean>;
    timeoutMs: number;
}

/** Sleep utility with adaptive delay. */
function sleep(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms));
}

/** Get extension instance. */
function getExtension(): vscode.Extension<unknown> | undefined {
    return vscode.extensions.getExtension('fangtype.fangtype');
}

/** Check if extension is present. */
async function checkExtensionPresent(): Promise<boolean> {
    const extension = getExtension();
    if (!extension) {
        return false;
    }
    console.log(`[Warmup] Extension found at: ${extension.extensionPath}`);
    return true;
}

/** Check if extension is active. */
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

/** Check if all required commands are registered. */
async function checkCommandsRegistered(): Promise<boolean> {
    const commands = await vscode.commands.getCommands();
    const requiredCommands = [
        'fangtype.insertTypeAtCursor',
        'fangtype.insertAllTypes',
        'fangtype.removeTypeAtCursor',
        'fangtype.removeAllTypes',
    ];

    const foundCommands = requiredCommands.filter(cmd => commands.includes(cmd));
    const allRegistered = foundCommands.length === requiredCommands.length;

    if (allRegistered) {
        console.log(`[Warmup] All ${requiredCommands.length} commands registered`);
    } else {
        // Log partial matches for debugging
        const fangtypeCommands = commands.filter(cmd => cmd.startsWith('fangtype.'));
        console.log(
            `[Warmup:Diag] Commands found: ${foundCommands.length}/${requiredCommands.length}. ` +
                `fangtype.* commands in registry: [${fangtypeCommands.join(', ')}]`
        );
    }

    return allRegistered;
}

/** Check the language client state, not inlay hints, so warmup stays cheap. */
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
        // Fall back: commands register only after server start, so active implies running.
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

/** Check output channel readiness (an active extension implies it exists). */
async function checkOutputChannelReady(): Promise<boolean> {
    const extension = getExtension();
    if (!extension?.isActive) {
        return false;
    }

    console.log(`[Warmup] Output channel ready`);
    return true;
}

/** Poll through activation stages until all are complete. */
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

        // Open a Python file once, before the active check, to trigger activation.
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

/** Warm inference once; never throws, reopens fresh docs so a cached empty result can't stall. */
async function warmupRealInference(
    budgetMs = 30000,
    pollIntervalMs = 500,
    reopenAfterMs = 5000
): Promise<void> {
    console.log('[Warmup] Warming up real inference...');

    const startTime = Date.now();
    let editor = await openPythonFile('warmup_x = 42\n');
    let lastReopen = startTime;

    try {
        while (Date.now() - startTime < budgetMs) {
            let hints: vscode.InlayHint[] = [];
            try {
                hints = await getInlayHints(editor.document);
            } catch (error) {
                console.log(
                    `[Warmup:Diag] getInlayHints rejected, treating as no hints yet: ${error}`
                );
            }
            if (hints.length > 0) {
                console.log(
                    `[Warmup] ✓ Real inference warm: received ${hints.length} hint(s) after ${Date.now() - startTime}ms`
                );
                return;
            }

            if (Date.now() - lastReopen >= reopenAfterMs) {
                await closeAllEditors();
                editor = await openPythonFile('warmup_x = 42\n');
                lastReopen = Date.now();
            }

            await sleep(pollIntervalMs);
        }

        console.log(
            `[Warmup] WARNING: no inlay hints received within ${budgetMs}ms budget; ` +
                `proceeding anyway (later tests may absorb inference cold-start).`
        );
    } finally {
        await closeAllEditors();
        await cleanupTempFiles();
    }
}

/** Perform global warmup with comprehensive stage polling. */
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

    // Pay real-inference cold-start once globally so per-test hint polls can use small timeouts.
    await warmupRealInference();

    warmupCompleted = true;
    console.log('[Warmup] ✓ Warmup complete');
}

// Global setup - runs once before all test suites
setup(async function () {
    this.timeout(150000);
    await performGlobalWarmup();
});

// Global teardown - runs once after all test suites
teardown(async () => {
    await closeAllEditors();
});
