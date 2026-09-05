import * as assert from 'assert';
import { parsePreflight, classifyClose } from '../../src/common/preflight';
import { needsDepsProbe } from '../../src/common/server';

suite('parsePreflight', () => {
    test('exit 0 with empty output means ok', () => {
        assert.deepStrictEqual(parsePreflight('', 0), { ok: true });
    });
    test('nonzero exit with names lists missing modules', () => {
        assert.deepStrictEqual(parsePreflight('mypy,librt', 1), {
            ok: false,
            missing: ['mypy', 'librt'],
        });
    });
    test('trims whitespace/newlines around names', () => {
        assert.deepStrictEqual(parsePreflight('  jedi \n', 1), {
            ok: false,
            missing: ['jedi'],
        });
    });
});

suite('classifyClose', () => {
    test('exit 0 with empty output means ok', () => {
        assert.deepStrictEqual(classifyClose('', 0, null), { ok: true });
    });
    test('nonzero exit with names still lists missing modules (M41 real-miss case)', () => {
        assert.deepStrictEqual(classifyClose('mypy,librt', 1, null), {
            ok: false,
            missing: ['mypy', 'librt'],
        });
    });
    test('nonzero exit with empty stdout is a crash, not a missing-deps report (M41)', () => {
        assert.deepStrictEqual(classifyClose('', 1, null), { ok: true });
    });
    test('signal-killed close (code null) fails open instead of coercing to success (M37/M38)', () => {
        assert.deepStrictEqual(classifyClose('', null, 'SIGTERM'), { ok: true });
    });
    test('signal-killed close with code null and signal null still fails open', () => {
        assert.deepStrictEqual(classifyClose('', null, null), { ok: true });
    });
});

suite('needsDepsProbe', () => {
    test('managed skips the probe, having just installed the deps itself', () => {
        assert.strictEqual(needsDepsProbe('managed'), false);
    });
    test('fromEnvironment probes', () => {
        assert.strictEqual(needsDepsProbe('fromEnvironment'), true);
    });
    test('useBundled probes too: nox vendors fangtype --no-deps, so no native dep ships', () => {
        assert.strictEqual(needsDepsProbe('useBundled'), true);
    });
});
