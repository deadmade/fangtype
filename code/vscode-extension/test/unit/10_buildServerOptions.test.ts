import * as assert from 'assert';
import * as path from 'path';
import { buildServerOptions, toVenvError } from '../../src/common/server';
import type { IServerPaths } from '../../src/common/server';
import type { ISettings } from '../../src/common/settings';
import { VenvError } from '../../src/common/venv';

/** Pure buildServerOptions: interpreter launch + PYTHONPATH order (useBundled prepends). */

/** Bundle paths injected so assertions do not depend on the real extension root. */
const PATHS: IServerPaths = {
    serverScript: '/bundle/tool/lsp_server.py',
    serverDebugScript: '/bundle/tool/lsp_runner.py',
    bundledLibs: '/bundle/libs',
    bundledTool: '/bundle/tool',
};

/** Minimal-but-complete `ISettings` factory; overrides win over the defaults. */
function makeSettings(overrides: Partial<ISettings> = {}): ISettings {
    return {
        cwd: '/work',
        workspace: 'file:///work',
        interpreter: [],
        installMode: 'managed',
        mypyEnabled: true,
        mypyInferenceValidationEnabled: false,
        diagnosticSeverity: 'information',
        crossFileContractsEnabled: true,
        logLevel: 'warning',
        ...overrides,
    };
}

suite('buildServerOptions Unit Test Suite', () => {
    test('normal interpreter path runs the bootstrap under the interpreter', () => {
        const settings = makeSettings({ interpreter: ['/usr/bin/python'] });

        const inv = buildServerOptions(settings, PATHS, { PYTHONPATH: undefined });

        assert.strictEqual(inv.command, '/usr/bin/python');
        assert.deepStrictEqual(inv.args, [PATHS.serverScript]);
    });

    test('multi-element interpreter argv keeps leading args before the script', () => {
        const settings = makeSettings({ interpreter: ['/usr/bin/env', 'python3'] });

        const inv = buildServerOptions(settings, PATHS, { PYTHONPATH: undefined });

        assert.strictEqual(inv.command, '/usr/bin/env');
        assert.deepStrictEqual(inv.args, ['python3', PATHS.serverScript]);
    });

    test('useBundled prepends the bundled dirs ahead of the inherited PYTHONPATH', () => {
        const settings = makeSettings({
            interpreter: ['/usr/bin/python'],
            installMode: 'useBundled',
        });

        const inv = buildServerOptions(settings, PATHS, { PYTHONPATH: '/inherited' });

        assert.strictEqual(inv.env.LS_IMPORT_STRATEGY, 'useBundled');
        assert.strictEqual(
            inv.env.PYTHONPATH,
            [PATHS.bundledLibs, PATHS.bundledTool, '/inherited'].join(path.delimiter)
        );
    });

    test('fromEnvironment appends the bundled dirs after the inherited PYTHONPATH', () => {
        const settings = makeSettings({
            interpreter: ['/usr/bin/python'],
            installMode: 'fromEnvironment',
        });

        const inv = buildServerOptions(settings, PATHS, { PYTHONPATH: '/inherited' });

        assert.strictEqual(inv.env.LS_IMPORT_STRATEGY, 'fromEnvironment');
        assert.strictEqual(
            inv.env.PYTHONPATH,
            ['/inherited', PATHS.bundledLibs, PATHS.bundledTool].join(path.delimiter)
        );
    });

    test('FANGTYPE_* vars are forwarded and FANGTYPE_ENGINE defaults to jedi', () => {
        const settings = makeSettings({ interpreter: ['/usr/bin/python'] });

        const withEngine = buildServerOptions(settings, PATHS, {
            PYTHONPATH: undefined,
            FANGTYPE_ENGINE: 'some-engine',
            FANGTYPE_FOO: 'bar',
        });
        assert.strictEqual(withEngine.env.FANGTYPE_ENGINE, 'some-engine');
        assert.strictEqual(withEngine.env.FANGTYPE_FOO, 'bar');

        const withoutEngine = buildServerOptions(settings, PATHS, { PYTHONPATH: undefined });
        assert.strictEqual(withoutEngine.env.FANGTYPE_ENGINE, 'jedi');
    });

    test('DEBUG_FANGTYPE switches to the debug runner and forwards the debug knobs', () => {
        const settings = makeSettings({ interpreter: ['/usr/bin/python'] });

        const inv = buildServerOptions(settings, PATHS, {
            PYTHONPATH: undefined,
            DEBUG_FANGTYPE: '1',
            DEBUG_FANGTYPE_PORT: '5679',
            DEBUG_FANGTYPE_WAIT: '1',
        });

        // The interpreter now runs the debug variant, not the plain bootstrap.
        assert.deepStrictEqual(inv.args, [PATHS.serverDebugScript]);
        assert.ok(
            !inv.args.includes(PATHS.serverScript),
            'debug launch must not run the non-debug server script'
        );
        // The debug knobs are forwarded into the server env.
        assert.strictEqual(inv.env.DEBUG_FANGTYPE, '1');
        assert.strictEqual(inv.env.DEBUG_FANGTYPE_PORT, '5679');
        assert.strictEqual(inv.env.DEBUG_FANGTYPE_WAIT, '1');
    });

    test('without DEBUG_FANGTYPE the launch is unchanged (plain script, no debug knobs)', () => {
        const settings = makeSettings({ interpreter: ['/usr/bin/python'] });

        const inv = buildServerOptions(settings, PATHS, { PYTHONPATH: undefined });

        assert.deepStrictEqual(inv.args, [PATHS.serverScript]);
        assert.strictEqual(inv.env.DEBUG_FANGTYPE, undefined);
        assert.strictEqual(inv.env.DEBUG_FANGTYPE_PORT, undefined);
        assert.strictEqual(inv.env.DEBUG_FANGTYPE_WAIT, undefined);
    });
});

suite('toVenvError', () => {
    test('passes an existing VenvError through unchanged (same instance, kind preserved)', () => {
        const original = new VenvError('network', 'connection reset');
        const result = toVenvError(original);
        assert.strictEqual(result, original);
        assert.strictEqual(result.kind, 'network');
    });

    test('wraps a plain thrown Error (e.g. ENOENT from a missing requirements file) as kind unknown', () => {
        const thrown = new Error("ENOENT: no such file or directory, open 'requirements.txt'");
        const result = toVenvError(thrown);
        assert.ok(result instanceof VenvError);
        assert.strictEqual(result.kind, 'unknown');
        assert.strictEqual(result.message, String(thrown));
    });

    test('wraps a non-Error thrown value too', () => {
        const result = toVenvError('boom');
        assert.ok(result instanceof VenvError);
        assert.strictEqual(result.kind, 'unknown');
        assert.strictEqual(result.message, 'boom');
    });
});
