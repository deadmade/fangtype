import { defineConfig } from '@vscode/test-cli';

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
		VSCODE_EXTENSION_TEST_MODE: 'true'
	}
});
