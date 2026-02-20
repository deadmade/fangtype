import * as vscode from 'vscode';
import * as assert from 'assert';
import * as path from 'path';
import * as fs from 'fs';

/**
 * Opens a Python file with given content and waits for extension activation.
 * @param content - Python source code
 * @param filename - Optional filename (default: temp file with timestamp)
 * @returns Promise<TextEditor>
 */
export async function openPythonFile(
    content: string,
    filename?: string
): Promise<vscode.TextEditor> {
    const uri = await createTempPythonFile(content, filename);
    const document = await vscode.workspace.openTextDocument(uri);
    const editor = await vscode.window.showTextDocument(document);

    // Wait a bit for the document to be fully loaded
    await sleep(100);

    return editor;
}

/**
 * Waits for LSP server to be ready (up to timeout).
 * Checks for inlay hints availability as readiness signal.
 * @param timeout - Max wait time in ms (default: 15000)
 */
export async function waitForLspReady(timeout = 15000): Promise<void> {
    const startTime = Date.now();

    while (Date.now() - startTime < timeout) {
        try {
            // Check if extension is active
            const extension = vscode.extensions.getExtension('auto-type.auto-type');
            if (extension && extension.isActive) {
                // Try to get inlay hints as a readiness check
                const editor = vscode.window.activeTextEditor;
                if (editor && editor.document.languageId === 'python') {
                    const hints = await vscode.commands.executeCommand<vscode.InlayHint[]>(
                        'vscode.executeInlayHintProvider',
                        editor.document.uri,
                        new vscode.Range(0, 0, 1, 0)
                    );

                    // If we got a response (even if empty), server is ready
                    if (hints !== undefined) {
                        return;
                    }
                }
            }
        } catch {
            // Ignore errors, keep trying
        }

        await sleep(200);
    }

    throw new Error(`LSP server did not become ready within ${timeout}ms`);
}

/**
 * Executes a VS Code command and returns result.
 * @param command - Command ID
 * @param args - Command arguments
 */
export async function executeCommand<T>(command: string, ...args: unknown[]): Promise<T> {
    return await vscode.commands.executeCommand<T>(command, ...args);
}

/**
 * Gets inlay hints for a document.
 * @param document - Text document
 * @param range - Optional range (default: full document)
 */
export async function getInlayHints(
    document: vscode.TextDocument,
    range?: vscode.Range
): Promise<vscode.InlayHint[]> {
    const targetRange = range || new vscode.Range(0, 0, document.lineCount, 0);

    const hints = await vscode.commands.executeCommand<vscode.InlayHint[]>(
        'vscode.executeInlayHintProvider',
        document.uri,
        targetRange
    );

    return hints || [];
}

/**
 * Sets cursor position in editor.
 * @param editor - Text editor
 * @param line - Line number (0-based)
 * @param character - Character position (0-based)
 */
export async function setCursorPosition(
    editor: vscode.TextEditor,
    line: number,
    character: number
): Promise<void> {
    const position = new vscode.Position(line, character);
    editor.selection = new vscode.Selection(position, position);

    // Reveal the position to ensure it's visible
    editor.revealRange(new vscode.Range(position, position));

    // Wait a bit for the selection to be processed
    await sleep(50);
}

/**
 * Waits for a condition to be true.
 * @param condition - Function returning boolean or Promise<boolean>
 * @param timeout - Max wait time (default: 5000ms)
 * @param interval - Check interval (default: 100ms)
 */
export async function waitForCondition(
    condition: () => boolean | Promise<boolean>,
    timeout = 5000,
    interval = 100
): Promise<void> {
    const startTime = Date.now();

    while (Date.now() - startTime < timeout) {
        const result = await Promise.resolve(condition());
        if (result) {
            return;
        }
        await sleep(interval);
    }

    throw new Error(`Condition not met within ${timeout}ms`);
}

/**
 * Compares code strings, ignoring whitespace differences.
 * Useful for verifying code transformations.
 */
export function assertCodeEqual(actual: string, expected: string): void {
    const normalize = (code: string) => {
        return code
            .split('\n')
            .map(line => line.trim())
            .filter(line => line.length > 0)
            .join('\n');
    };

    const normalizedActual = normalize(actual);
    const normalizedExpected = normalize(expected);

    assert.strictEqual(
        normalizedActual,
        normalizedExpected,
        `Code does not match.\nExpected:\n${expected}\n\nActual:\n${actual}`
    );
}

/**
 * Creates a temporary Python file in the test workspace.
 * File is tracked for cleanup after test suite.
 */
const tempFiles: vscode.Uri[] = [];

export async function createTempPythonFile(content: string, name?: string): Promise<vscode.Uri> {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
        throw new Error('No workspace folder available for test files');
    }

    const filename = name || `test_${Date.now()}_${crypto.randomUUID()}.py`;
    const srcDir = path.join(workspaceFolder.uri.fsPath, 'src');
    const filePath = path.join(srcDir, filename);

    // Ensure src directory exists
    if (!fs.existsSync(srcDir)) {
        fs.mkdirSync(srcDir, { recursive: true });
    }

    // Write file
    fs.writeFileSync(filePath, content, 'utf8');

    const uri = vscode.Uri.file(filePath);
    tempFiles.push(uri);

    return uri;
}

/**
 * Closes all open editors without saving.
 */
export async function closeAllEditors(): Promise<void> {
    await vscode.commands.executeCommand('workbench.action.closeAllEditors');
    await sleep(100); // Wait for editors to close

    // Additional cleanup: dismiss any open notifications or dialogs
    try {
        await vscode.commands.executeCommand('notifications.clearAll');
    } catch {
        // Ignore errors - command might not be available
    }
}

/**
 * Reverts document to original content without saving.
 */
export async function revertDocument(document: vscode.TextDocument): Promise<void> {
    await vscode.commands.executeCommand('workbench.action.files.revert', document.uri);
    await sleep(50);
}

/**
 * Cleans up all temporary test files.
 */
export async function cleanupTempFiles(): Promise<void> {
    for (const uri of tempFiles) {
        try {
            if (fs.existsSync(uri.fsPath)) {
                fs.unlinkSync(uri.fsPath);
            }
        } catch (error) {
            console.warn(`Failed to cleanup temp file ${uri.fsPath}:`, error);
        }
    }
    tempFiles.length = 0;
}

/**
 * Cleans the workspace by removing test artifacts while preserving project structure.
 * Removes .mypy_cache and all contents of src/ directory, but keeps project config files.
 */
export async function cleanWorkspace(): Promise<void> {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
        return;
    }

    const folderPath = workspaceFolder.uri.fsPath;

    try {
        // Remove .mypy_cache directory
        const mypyCachePath = path.join(folderPath, '.mypy_cache');
        if (fs.existsSync(mypyCachePath)) {
            fs.rmSync(mypyCachePath, { recursive: true, force: true });
        }

        // Clean src/ directory contents but keep the directory
        const srcPath = path.join(folderPath, 'src');
        if (fs.existsSync(srcPath)) {
            const srcItems = fs.readdirSync(srcPath);
            for (const item of srcItems) {
                const itemPath = path.join(srcPath, item);
                try {
                    fs.rmSync(itemPath, { recursive: true, force: true });
                } catch (error) {
                    console.warn(`Failed to remove src item ${itemPath}:`, error);
                }
            }
        }
    } catch (error) {
        console.warn(`Failed to clean workspace ${folderPath}:`, error);
    }

    // Clear tracked temp files as they are gone
    tempFiles.length = 0;
}

/**
 * Sets up the workspace with necessary project files.
 * Creates pyproject.toml, README.md, .gitignore, and src/ directory.
 */
export async function setupWorkspace(): Promise<void> {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
        throw new Error('No workspace folder available');
    }

    const folderPath = workspaceFolder.uri.fsPath;

    // Create src/ directory
    const srcPath = path.join(folderPath, 'src');
    if (!fs.existsSync(srcPath)) {
        fs.mkdirSync(srcPath, { recursive: true });
    }

    // Create pyproject.toml
    const pyprojectContent = `[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "test-project"
version = "0.1.0"
description = "Test project for auto-type extension"
readme = "README.md"
requires-python = ">=3.10"
license = {text = "MIT"}
authors = [
    {name = "Test Author", email = "test@example.com"}
]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
]

[project.optional-dependencies]
dev = [
    "pytest",
    "mypy",
    "ruff",
]

[tool.mypy]
python_version = "3.10"
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true

[tool.ruff]
line-length = 100
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "D", "UP", "B", "C4", "SIM"]
ignore = ["D100", "D104"]
`;
    fs.writeFileSync(path.join(folderPath, 'pyproject.toml'), pyprojectContent, 'utf8');

    // Create README.md
    const readmeContent = `# Test Project

This is a test project for the auto-type VS Code extension.

## Structure

- \`src/\` - Source code directory where test Python files are created during extension testing

## Usage

This project serves as a workspace for testing the auto-type extension's type annotation features.
`;
    fs.writeFileSync(path.join(folderPath, 'README.md'), readmeContent, 'utf8');

    // Create .gitignore
    const gitignoreContent = `# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
share/python-wheels/
*.egg-info/
.installed.cfg
*.egg
MANIFEST

# Virtual environments
.env
.venv
env/
venv/
ENV/
env.bak/
venv.bak/

# IDE
.vscode/
.idea/
*.swp
*.swo
*~

# Testing
.pytest_cache/
.coverage
htmlcov/
.tox/
.nox/

# MyPy
.mypy_cache/
.dmypy.json
dmypy.json

# Ruff
.ruff_cache/

# Type annotations (generated during tests)
*.pyi
`;
    fs.writeFileSync(path.join(folderPath, '.gitignore'), gitignoreContent, 'utf8');
}

/**
 * Full test cleanup - closes editors and cleans temp files.
 */
export async function fullTestCleanup(): Promise<void> {
    await closeAllEditors();
    await cleanupTempFiles();
    await sleep(200);
}

/**
 * Ensures test isolation by cleaning up state.
 */
export async function ensureTestIsolation(): Promise<void> {
    // Close all editors
    await closeAllEditors();

    // Clear any selections or focus
    await sleep(100);

    // Give LSP time to settle
    await sleep(200);
}

/**
 * Simple sleep utility.
 */
export function sleep(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Gets the text content of a document.
 */
export function getDocumentText(document: vscode.TextDocument): string {
    return document.getText();
}

/**
 * Waits for document to have specific content.
 */
export async function waitForDocumentContent(
    document: vscode.TextDocument,
    expectedContent: string,
    timeout = 3000
): Promise<void> {
    await waitForCondition(() => {
        const content = document.getText();
        return content.includes(expectedContent);
    }, timeout);
}

/**
 * Gets line text from document.
 */
export function getLineText(document: vscode.TextDocument, lineNumber: number): string {
    if (lineNumber >= document.lineCount) {
        throw new Error(`Line ${lineNumber} does not exist in document`);
    }
    return document.lineAt(lineNumber).text;
}

/**
 * Waits for a specific number of inlay hints to appear.
 * Uses retry mechanism to handle LSP timing issues.
 */
export async function waitForInlayHints(
    document: vscode.TextDocument,
    expectedCount: number,
    timeout = 10000
): Promise<vscode.InlayHint[]> {
    let hints: vscode.InlayHint[] = [];

    await waitForCondition(
        async () => {
            hints = await getInlayHintsWithRetry(document);
            return hints.length >= expectedCount;
        },
        timeout,
        500 // Check every 500ms
    );

    return hints;
}

/**
 * Gets inlay hints with retry logic for reliability.
 */
export async function getInlayHintsWithRetry(
    document: vscode.TextDocument,
    range?: vscode.Range,
    maxRetries = 3
): Promise<vscode.InlayHint[]> {
    for (let attempt = 0; attempt < maxRetries; attempt++) {
        try {
            const hints = await getInlayHints(document, range);
            return hints;
        } catch (error) {
            if (attempt === maxRetries - 1) {
                throw error;
            }
            // Wait a bit before retrying
            await sleep(200);
        }
    }
    return [];
}

/**
 * Retries an async operation with exponential backoff.
 */
export async function retryOperation<T>(
    operation: () => Promise<T>,
    maxRetries = 3,
    initialDelay = 200
): Promise<T> {
    let lastError: Error | undefined;

    for (let attempt = 0; attempt < maxRetries; attempt++) {
        try {
            return await operation();
        } catch (error) {
            lastError = error as Error;
            if (attempt < maxRetries - 1) {
                // Exponential backoff
                const delay = initialDelay * Math.pow(2, attempt);
                await sleep(delay);
            }
        }
    }

    throw lastError || new Error('Operation failed after retries');
}

/**
 * Finds a word position in document (for cursor placement).
 */
export function findWordPosition(
    document: vscode.TextDocument,
    word: string
): vscode.Position | null {
    for (let i = 0; i < document.lineCount; i++) {
        const lineText = document.lineAt(i).text;
        const index = lineText.indexOf(word);
        if (index !== -1) {
            return new vscode.Position(i, index);
        }
    }
    return null;
}

/**
 * Waits for document to be saved and synced with LSP.
 */
export async function waitForDocumentSync(
    document: vscode.TextDocument,
    timeout = 3000
): Promise<void> {
    // Wait for document to not be dirty (if it was saved)
    await waitForCondition(() => !document.isDirty, timeout, 100).catch(() => {
        // Ignore timeout - document might not need saving
    });

    // Additional wait for LSP to process changes
    await sleep(200);
}

/**
 * Waits for workspace edit to be applied.
 */
export async function waitForEditApplied(
    document: vscode.TextDocument,
    expectedChange: (text: string) => boolean,
    timeout = 5000
): Promise<void> {
    await waitForCondition(
        () => {
            const text = document.getText();
            return expectedChange(text);
        },
        timeout,
        100
    );
}

/**
 * Executes a command with retry logic for reliability.
 */
export async function executeCommandWithRetry<T>(
    command: string,
    args: unknown[] = [],
    maxRetries = 3
): Promise<T | undefined> {
    return retryOperation(async () => {
        return await vscode.commands.executeCommand<T>(command, ...args);
    }, maxRetries);
}

/**
 * Waits for document change event after an operation.
 */
export async function waitForDocumentChange(
    document: vscode.TextDocument,
    operation: () => Promise<void>,
    timeout = 5000
): Promise<void> {
    let changed = false;

    const disposable = vscode.workspace.onDidChangeTextDocument(event => {
        if (event.document.uri.toString() === document.uri.toString()) {
            changed = true;
        }
    });

    try {
        // Execute the operation
        await operation();

        // Wait for change event
        await waitForCondition(() => changed, timeout, 100);
    } finally {
        disposable.dispose();
    }
}

/**
 * Logs debug information if verbose mode is enabled.
 */
export function debugLog(message: string, ...args: unknown[]): void {
    // Always log in test environment with timestamp
    const timestamp = new Date().toISOString();
    console.log(`[${timestamp}] [TEST] ${message}`, ...args);
}

/**
 * Logs timing information for operations.
 */
export async function measureOperation<T>(name: string, operation: () => Promise<T>): Promise<T> {
    const start = Date.now();
    debugLog(`Starting: ${name}`);

    try {
        const result = await operation();
        const duration = Date.now() - start;
        debugLog(`Completed: ${name} (${duration}ms)`);
        return result;
    } catch (error) {
        const duration = Date.now() - start;
        debugLog(`Failed: ${name} (${duration}ms)`, error);
        throw error;
    }
}

/**
 * Logs document state for debugging.
 */
export function logDocumentState(document: vscode.TextDocument, label = 'Document'): void {
    debugLog(`${label} state:`, {
        uri: document.uri.toString(),
        languageId: document.languageId,
        lineCount: document.lineCount,
        isDirty: document.isDirty,
        isClosed: document.isClosed,
        version: document.version,
        content: document.getText(),
    });
}

/**
 * Logs current test context for debugging failures.
 */
export async function logTestContext(label: string): Promise<void> {
    const editor = vscode.window.activeTextEditor;
    const extension = vscode.extensions.getExtension('auto-type.auto-type');

    debugLog(`=== Test Context: ${label} ===`);
    debugLog(`Extension active: ${extension?.isActive}`);
    debugLog(`Active editor: ${editor ? editor.document.uri.toString() : 'none'}`);
    debugLog(`Language: ${editor?.document.languageId || 'n/a'}`);
    debugLog(`Document lines: ${editor?.document.lineCount || 0}`);

    if (editor) {
        try {
            const hints = await getInlayHints(editor.document);
            debugLog(`Inlay hints available: ${hints.length}`);
        } catch (e) {
            debugLog(`Inlay hints error: ${e}`);
        }
    }
    debugLog(`=== End Context ===`);
}

// ============================================================================
// INSERTION VERIFICATION HELPERS
// ============================================================================

/**
 * Result of an insertion operation with verification.
 */
export interface InsertionVerificationResult {
    /** Whether the expected pattern was found in the document */
    success: boolean;
    /** The actual text content after the operation */
    actualText: string;
    /** The original text before the operation */
    originalText: string;
    /** Whether the document version changed (edit was applied) */
    documentChanged: boolean;
    /** Time taken for the operation in milliseconds */
    duration: number;
    /** Error message if the operation failed */
    errorMessage?: string;
}

/**
 * Waits for document text to contain a specific string.
 * Uses polling to reliably detect changes.
 *
 * @param document - The text document to monitor
 * @param expected - The string to wait for
 * @param timeout - Maximum wait time in ms (default: 10000)
 * @returns True if the expected string was found, false otherwise
 */
export async function waitForDocumentContains(
    document: vscode.TextDocument,
    expected: string,
    timeout = 10000
): Promise<boolean> {
    const start = Date.now();
    while (Date.now() - start < timeout) {
        const text = document.getText();
        if (text.includes(expected)) {
            debugLog(`Found expected text after ${Date.now() - start}ms`);
            return true;
        }
        await sleep(150);
    }
    debugLog(`Timeout waiting for text: "${expected}"`);
    return false;
}

/**
 * Waits for document text to match a regular expression.
 * Uses polling to reliably detect changes.
 *
 * @param document - The text document to monitor
 * @param pattern - The regex pattern to match
 * @param timeout - Maximum wait time in ms (default: 10000)
 * @returns True if the pattern was matched, false otherwise
 */
export async function waitForDocumentMatches(
    document: vscode.TextDocument,
    pattern: RegExp,
    timeout = 10000
): Promise<boolean> {
    const start = Date.now();
    while (Date.now() - start < timeout) {
        const text = document.getText();
        if (pattern.test(text)) {
            debugLog(`Found pattern match after ${Date.now() - start}ms`);
            return true;
        }
        await sleep(150);
    }
    debugLog(`Timeout waiting for pattern: ${pattern}`);
    return false;
}

/**
 * Waits for document version to change, indicating an edit was applied.
 *
 * @param document - The text document to monitor
 * @param originalVersion - The version to compare against
 * @param timeout - Maximum wait time in ms (default: 10000)
 * @returns True if version changed, false otherwise
 */
export async function waitForDocumentVersionChange(
    document: vscode.TextDocument,
    originalVersion: number,
    timeout = 10000
): Promise<boolean> {
    const start = Date.now();
    while (Date.now() - start < timeout) {
        if (document.version > originalVersion) {
            debugLog(`Document version changed: ${originalVersion} -> ${document.version}`);
            return true;
        }
        await sleep(100);
    }
    debugLog(`Timeout waiting for version change from ${originalVersion}`);
    return false;
}

/**
 * Executes an insertion command and verifies the result.
 * This is the main helper for reliable insertion testing.
 *
 * @param editor - The active text editor
 * @param command - The VS Code command to execute
 * @param expectedPattern - String or regex pattern expected in the result
 * @param timeout - Maximum wait time in ms (default: 15000)
 * @returns Detailed result of the insertion verification
 */
export async function executeInsertionAndVerify(
    editor: vscode.TextEditor,
    command: string,
    expectedPattern: RegExp | string,
    timeout = 15000
): Promise<InsertionVerificationResult> {
    const start = Date.now();
    const originalText = editor.document.getText();
    const originalVersion = editor.document.version;

    debugLog(`Executing command: ${command}`);
    debugLog(`Original text: "${originalText.substring(0, 100)}..."`);
    debugLog(`Expected pattern: ${expectedPattern}`);

    try {
        // Execute the command
        await vscode.commands.executeCommand(command);

        // Wait for document version to change (primary indicator of edit)
        const documentChanged = await waitForDocumentVersionChange(
            editor.document,
            originalVersion,
            timeout
        );

        // Give extra time for LSP processing
        await sleep(300);

        const actualText = editor.document.getText();
        const duration = Date.now() - start;

        // Check if pattern matches
        const matches =
            typeof expectedPattern === 'string'
                ? actualText.includes(expectedPattern)
                : expectedPattern.test(actualText);

        debugLog(`Actual text: "${actualText.substring(0, 100)}..."`);
        debugLog(`Document changed: ${documentChanged}, Pattern matches: ${matches}`);

        if (!matches) {
            return {
                success: false,
                actualText,
                originalText,
                documentChanged,
                duration,
                errorMessage: documentChanged
                    ? `Document changed but expected pattern not found. Looking for: "${expectedPattern}"`
                    : `Document did not change. LSP may not have responded. Looking for: "${expectedPattern}"`,
            };
        }

        return {
            success: true,
            actualText,
            originalText,
            documentChanged,
            duration,
        };
    } catch (error) {
        return {
            success: false,
            actualText: editor.document.getText(),
            originalText,
            documentChanged: false,
            duration: Date.now() - start,
            errorMessage: `Command execution failed: ${error}`,
        };
    }
}

/**
 * Executes insertTypeAtCursor and verifies the type was inserted.
 * Convenience wrapper for the common insertion test case.
 *
 * @param editor - The active text editor
 * @param variableName - Name of the variable being annotated
 * @param expectedType - The expected type annotation
 * @param timeout - Maximum wait time in ms (default: 15000)
 * @returns Detailed result of the insertion verification
 */
export async function insertTypeAndVerify(
    editor: vscode.TextEditor,
    variableName: string,
    expectedType: string,
    timeout = 15000
): Promise<InsertionVerificationResult> {
    // Build the expected pattern: "variableName: type ="
    const expectedPattern = new RegExp(
        `${escapeRegExp(variableName)}\\s*:\\s*${escapeRegExp(expectedType)}\\s*=`
    );

    return executeInsertionAndVerify(
        editor,
        'autoType.insertTypeAtCursor',
        expectedPattern,
        timeout
    );
}

/**
 * Escapes special regex characters in a string.
 */
function escapeRegExp(string: string): string {
    return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Verifies that a type annotation exists in the document.
 *
 * @param document - The text document to check
 * @param variableName - The variable name to look for
 * @param expectedType - The expected type (can be partial match)
 * @returns True if the annotation exists
 */
export function verifyTypeAnnotation(
    document: vscode.TextDocument,
    variableName: string,
    expectedType: string
): boolean {
    const text = document.getText();
    const pattern = new RegExp(
        `${escapeRegExp(variableName)}\\s*:\\s*${escapeRegExp(expectedType)}`
    );
    return pattern.test(text);
}

/**
 * Gets all type annotations from a document as a map of variable -> type.
 * Uses a simple regex-based approach for test verification.
 *
 * @param document - The text document to analyze
 * @returns Map of variable names to their type annotations
 */
export function extractTypeAnnotations(document: vscode.TextDocument): Map<string, string> {
    const text = document.getText();
    const annotations = new Map<string, string>();

    // Match variable annotations: name: type = value
    const varPattern = /(\w+)\s*:\s*([^=\n]+?)\s*=/g;
    let match;
    while ((match = varPattern.exec(text)) !== null) {
        const varName = match[1];
        const varType = match[2];
        if (varName && varType) {
            annotations.set(varName, varType.trim());
        }
    }

    return annotations;
}

/**
 * Compares expected annotations against actual document content.
 *
 * @param document - The text document to check
 * @param expected - Map of variable names to expected types
 * @returns Object with matched, missing, and extra annotations
 */
export function compareAnnotations(
    document: vscode.TextDocument,
    expected: Map<string, string>
): {
    matched: string[];
    missing: string[];
    extra: string[];
    mismatched: { variable: string; expected: string; actual: string }[];
} {
    const actual = extractTypeAnnotations(document);
    const matched: string[] = [];
    const missing: string[] = [];
    const mismatched: { variable: string; expected: string; actual: string }[] = [];

    for (const [variable, expectedType] of expected) {
        const actualType = actual.get(variable);
        if (!actualType) {
            missing.push(variable);
        } else if (actualType !== expectedType) {
            mismatched.push({ variable, expected: expectedType, actual: actualType });
        } else {
            matched.push(variable);
        }
    }

    const extra = Array.from(actual.keys()).filter(v => !expected.has(v));

    return { matched, missing, extra, mismatched };
}

/**
 * Waits for the server to be healthy and ready for insertion operations.
 * This is more thorough than just checking for hints.
 *
 * @param editor - The text editor with the document
 * @param expectedHints - Minimum number of hints expected
 * @param timeout - Maximum wait time in ms (default: 30000)
 */
export async function waitForServerReadyForInsertion(
    editor: vscode.TextEditor,
    expectedHints = 1,
    _timeout = 30000
): Promise<vscode.InlayHint[]> {
    debugLog('Waiting for server to be ready for insertion...');

    return retryOperation(
        async () => {
            const hints = await waitForInlayHints(editor.document, expectedHints, _timeout);
            if (hints.length < expectedHints) {
                throw new Error(`Expected ${expectedHints} hints, got ${hints.length}`);
            }
            debugLog(`Server ready with ${hints.length} hints`);
            return hints;
        },
        3,
        1000
    );
}
