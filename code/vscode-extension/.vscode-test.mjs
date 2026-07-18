import { defineConfig } from '@vscode/test-cli';
import { execSync } from 'node:child_process';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

const rootDir = path.dirname(fileURLToPath(import.meta.url));

/**
 * Resolve the Python interpreter the launched server should run under.
 *
 * The bare electron test instance ships without `ms-python.python`, so the
 * extension cannot resolve an interpreter itself — the harness must supply one.
 * This config is evaluated by `vscode-test` under Node (inside `nix develop`),
 * so `process.execPath` is Node, not Python; resolve Python explicitly.
 *
 * Precedence: `FANGTYPE_INTERPRETER` (explicit override) → `python` on PATH
 * (the Nix dev shell's 3.14 with pygls/jedi/libcst/mypy/injector) → `python3`.
 */
function resolveInterpreter() {
	const fromEnv = process.env.FANGTYPE_INTERPRETER;
	if (fromEnv && fromEnv.trim()) {
		return fromEnv.trim();
	}
	for (const candidate of ['python', 'python3']) {
		try {
			return execSync(`command -v ${candidate}`, { encoding: 'utf8' }).trim();
		} catch {
			// try the next candidate
		}
	}
	return 'python';
}

const interpreter = resolveInterpreter();

// Write the test workspace settings so the extension resolves the interpreter
// from `fangtype.interpreter` (there is no ms-python in the test instance) and
// launches the server from source with `fromEnvironment` — under that strategy
// the inherited PYTHONPATH (which carries `code/lsp/src` in the Nix shell)
// supplies the `fangtype` package and its deps, so `bundled/libs` is not needed.
// `workspace/.vscode/` is git-ignored, so this generated file is never committed.
const vscodeDir = path.join(rootDir, 'workspace', '.vscode');
fs.mkdirSync(vscodeDir, { recursive: true });
fs.writeFileSync(
	path.join(vscodeDir, 'settings.json'),
	`${JSON.stringify(
		{
			'fangtype.interpreter': [interpreter],
			'fangtype.importStrategy': 'fromEnvironment',
			// The harness launches the server from source under the Nix interpreter; keep the
			// old fromEnvironment path (not the managed venv, which would pip-install natively).
			'fangtype.installMode': 'fromEnvironment',
		},
		null,
		4
	)}\n`
);

console.log(`[vscode-test] launching the Fangtype server from source under: ${interpreter}`);

export default defineConfig({
	files: 'test/suite/**/*.test.ts',
	mocha: {
		ui: 'tdd',
		timeout: 120000,
		slow: 15000,
		bail: false,
		reporter: 'mocha-junit-reporter',
		reporterOptions: {
			mochaFile: './test-results.xml'
		},
		require: ['tsx/cjs'],
	},
	workspaceFolder: './workspace',
	launchArgs: [
		//'--verbose',       // Enables verbose logging
		//'--log=debug'      // Sets specific log level (trace, debug, info, warn, error)
	],
	env: {
		VSCODE_EXTENSION_TEST_MODE: 'true',
		// Fallback for `getInterpreterFromSetting`/`resolveInterpreter` when the
		// `fangtype.interpreter` setting is empty and ms-python is absent.
		FANGTYPE_INTERPRETER: interpreter,
		// Forward the shell PYTHONPATH (code/lsp/src) so the spawned server, under
		// `fromEnvironment`, imports `fangtype` from source without a bundle.
		PYTHONPATH: process.env.PYTHONPATH ?? ''
	}
});
