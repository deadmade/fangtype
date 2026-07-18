import * as assert from 'assert';
import * as fs from 'fs';
import { createRequire } from 'module';
import * as os from 'os';
import * as path from 'path';

/** Real, mutable 'fs' module object — `import * as fs` gives a getter-wrapped live binding that
 *  can't be reassigned; stubbing a method for one test needs the underlying CJS module object. */
const mutableFs: typeof fs = createRequire(__filename)('fs');
import {
    acquireVenvLock,
    buildVenvCreateArgv,
    buildVenvInstallArgv,
    buildVenvPaths,
    closeCodeFor,
    computeRequirementsHash,
    isStaleLock,
    parseInterpreterVersion,
    parseVenvBuildError,
    releaseLockSync,
    tryAcquireLockSync,
    venvNeedsRebuild,
    VENV_STAMP_SCHEMA_VERSION,
} from '../../src/common/venv';
import type { IVenvStamp } from '../../src/common/venv';

/** Pure venv helpers: OS layout, rebuild decision, argv shapes, stderr classifier. No spawning. */

function makeStamp(overrides: Partial<IVenvStamp> = {}): IVenvStamp {
    return {
        schemaVersion: VENV_STAMP_SCHEMA_VERSION,
        basePython: '/usr/bin/python3',
        pythonVersion: '3.12.4',
        pythonVersionMinor: '3.12',
        requirementsHash: 'sha256:abc',
        createdAt: '2026-01-01T00:00:00.000Z',
        ...overrides,
    };
}

suite('buildVenvPaths', () => {
    test('posix layout uses bin/python and keys by minor version', () => {
        const p = buildVenvPaths('/gs', '3.12', 'linux');
        assert.strictEqual(p.venvDir, '/gs/venvs/py3.12');
        assert.strictEqual(p.pythonExe, '/gs/venvs/py3.12/bin/python');
        assert.strictEqual(p.stampFile, '/gs/venvs/py3.12/.fangtype-venv.json');
    });

    test('win32 layout uses Scripts\\python.exe', () => {
        const p = buildVenvPaths('C:\\gs', '3.13', 'win32');
        assert.strictEqual(p.venvDir, 'C:\\gs\\venvs\\py3.13');
        assert.strictEqual(p.pythonExe, 'C:\\gs\\venvs\\py3.13\\Scripts\\python.exe');
        assert.strictEqual(p.stampFile, 'C:\\gs\\venvs\\py3.13\\.fangtype-venv.json');
    });
});

suite('venvNeedsRebuild', () => {
    test('null stamp needs rebuild', () => {
        assert.strictEqual(venvNeedsRebuild(null, '3.12', 'sha256:abc'), true);
    });
    test('all-matching stamp does not need rebuild', () => {
        assert.strictEqual(venvNeedsRebuild(makeStamp(), '3.12', 'sha256:abc'), false);
    });
    test('schema mismatch needs rebuild', () => {
        assert.strictEqual(
            venvNeedsRebuild(makeStamp({ schemaVersion: 0 }), '3.12', 'sha256:abc'),
            true
        );
    });
    test('minor-version mismatch needs rebuild', () => {
        assert.strictEqual(venvNeedsRebuild(makeStamp(), '3.13', 'sha256:abc'), true);
    });
    test('requirements-hash mismatch needs rebuild', () => {
        assert.strictEqual(venvNeedsRebuild(makeStamp(), '3.12', 'sha256:xyz'), true);
    });
});

suite('buildVenvCreateArgv / buildVenvInstallArgv', () => {
    test('create argv runs -m venv against the target dir', () => {
        assert.deepStrictEqual(buildVenvCreateArgv(['/usr/bin/python3'], '/gs/venvs/py3.12'), [
            '/usr/bin/python3',
            '-m',
            'venv',
            '/gs/venvs/py3.12',
        ]);
    });
    test('create argv preserves leading interpreter args', () => {
        assert.deepStrictEqual(buildVenvCreateArgv(['py', '-3.12'], '/v'), [
            'py',
            '-3.12',
            '-m',
            'venv',
            '/v',
        ]);
    });
    test('install argv is plain (no shell quoting, no PowerShell &)', () => {
        const argv = buildVenvInstallArgv('/v/bin/python', '/ext/bundled/requirements.txt');
        assert.deepStrictEqual(argv, [
            '/v/bin/python',
            '-m',
            'pip',
            'install',
            '-r',
            '/ext/bundled/requirements.txt',
        ]);
        // Unlike buildInstallCommand, nothing is quoted and there is no leading '& '.
        assert.ok(!argv.some(a => a.startsWith('&') || a.includes('"')));
    });
});

suite('parseVenvBuildError', () => {
    test('classifies a missing venv/ensurepip module (Debian)', () => {
        assert.strictEqual(
            parseVenvBuildError(
                'The virtual environment was not created successfully because ensurepip is not available.'
            ),
            'missing-venv-module'
        );
        assert.strictEqual(parseVenvBuildError('No module named venv'), 'missing-venv-module');
    });
    test('classifies network failures', () => {
        assert.strictEqual(
            parseVenvBuildError('Could not find a version that satisfies the requirement'),
            'network'
        );
        assert.strictEqual(parseVenvBuildError('Temporary failure in name resolution'), 'network');
    });
    test('falls back to unknown', () => {
        assert.strictEqual(parseVenvBuildError('some other error'), 'unknown');
    });
});

suite('computeRequirementsHash', () => {
    test('is deterministic and prefixed', () => {
        const a = computeRequirementsHash('mypy==1.20.1\n');
        const b = computeRequirementsHash('mypy==1.20.1\n');
        assert.strictEqual(a, b);
        assert.ok(a.startsWith('sha256:'));
    });
    test('changes when contents change', () => {
        assert.notStrictEqual(
            computeRequirementsHash('mypy==1.20.1\n'),
            computeRequirementsHash('mypy==1.20.2\n')
        );
    });
});

suite('closeCodeFor', () => {
    test('signal-killed child (code null, signal set) maps to -1, never a false success', () => {
        assert.strictEqual(closeCodeFor(null, 'SIGKILL'), -1);
    });
    test('normal exit passes the real code through unchanged', () => {
        assert.strictEqual(closeCodeFor(0, null), 0);
        assert.strictEqual(closeCodeFor(1, null), 1);
    });
    test('null code with no signal falls back to success (unchanged prior behavior)', () => {
        assert.strictEqual(closeCodeFor(null, null), 0);
    });
});

suite('parseInterpreterVersion', () => {
    test('parses major.minor.micro into full + minor', () => {
        assert.deepStrictEqual(parseInterpreterVersion('3.12.4\n'), {
            full: '3.12.4',
            minor: '3.12',
        });
    });
    test('returns null on garbage', () => {
        assert.strictEqual(parseInterpreterVersion('not a version'), null);
        assert.strictEqual(parseInterpreterVersion('3.12'), null);
    });
});

/** Cross-process lock (M8/M9): O_EXCL create + mtime-based staleness, against a real tmp dir. */
suite('venv cross-process lock', () => {
    let dir: string;
    let lockPath: string;

    setup(() => {
        dir = fs.mkdtempSync(path.join(os.tmpdir(), 'fangtype-venv-lock-'));
        lockPath = path.join(dir, 'venv.lock');
    });

    teardown(() => {
        fs.rmSync(dir, { recursive: true, force: true });
    });

    suite('isStaleLock', () => {
        test('fresh mtime is not stale', () => {
            assert.strictEqual(isStaleLock(1000, 1000 + 5_000, 10_000), false);
        });
        test('mtime older than the threshold is stale', () => {
            assert.strictEqual(isStaleLock(1000, 1000 + 20_000, 10_000), true);
        });
    });

    suite('tryAcquireLockSync / releaseLockSync', () => {
        test('acquire creates the lockfile and succeeds', () => {
            assert.strictEqual(tryAcquireLockSync(lockPath), true);
            assert.strictEqual(fs.existsSync(lockPath), true);
        });
        test('acquire fails while another holder has the lock (EEXIST)', () => {
            assert.strictEqual(tryAcquireLockSync(lockPath), true);
            assert.strictEqual(tryAcquireLockSync(lockPath), false);
        });
        test('release removes the lockfile', () => {
            tryAcquireLockSync(lockPath);
            releaseLockSync(lockPath);
            assert.strictEqual(fs.existsSync(lockPath), false);
        });
        test('release on a missing lockfile does not throw', () => {
            assert.doesNotThrow(() => releaseLockSync(lockPath));
        });
        test('acquire succeeds again after release', () => {
            tryAcquireLockSync(lockPath);
            releaseLockSync(lockPath);
            assert.strictEqual(tryAcquireLockSync(lockPath), true);
        });
    });

    suite('acquireVenvLock', () => {
        test('acquires immediately when unheld', async () => {
            const acquired = await acquireVenvLock(lockPath, { maxWaitMs: 1000 });
            assert.strictEqual(acquired, true);
            assert.strictEqual(fs.existsSync(lockPath), true);
        });

        test('reclaims a stale lock (old mtime) instead of waiting it out', async () => {
            tryAcquireLockSync(lockPath);
            const old = Date.now() - 20_000;
            fs.utimesSync(lockPath, old / 1000, old / 1000);
            const acquired = await acquireVenvLock(lockPath, {
                maxWaitMs: 500,
                pollIntervalMs: 20,
                staleMs: 10_000,
            });
            assert.strictEqual(acquired, true);
        });

        test('gives up after maxWaitMs when a fresh lock is genuinely held', async () => {
            tryAcquireLockSync(lockPath); // fresh mtime -> never stale within this test
            const acquired = await acquireVenvLock(lockPath, {
                maxWaitMs: 150,
                pollIntervalMs: 20,
                staleMs: 10_000,
            });
            assert.strictEqual(acquired, false);
            assert.strictEqual(fs.existsSync(lockPath), true); // never rmSync'd the live holder's lock
        });

        test('does not busy-loop past maxWaitMs under repeated stat churn (catch path)', async () => {
            // Holds the lock for the whole test so tryAcquireLockSync always sees EEXIST; a
            // stubbed statSync then forces the `catch { continue }` path on every iteration for
            // a bounded churn window well past maxWaitMs, simulating pathological lock churn.
            // Pre-fix, that path skipped the deadline check, so the wait blew past maxWaitMs;
            // post-fix, the top-of-loop check bounds it regardless of how long the churn lasts.
            tryAcquireLockSync(lockPath);
            const origStatSync = mutableFs.statSync;
            const start = Date.now();
            const maxWaitMs = 100;
            const churnWindowMs = maxWaitMs * 4;
            mutableFs.statSync = ((...args: Parameters<typeof fs.statSync>) => {
                if (Date.now() - start < churnWindowMs) {
                    throw Object.assign(new Error('ENOENT'), { code: 'ENOENT' });
                }
                return (origStatSync as (...a: Parameters<typeof fs.statSync>) => fs.Stats)(
                    ...args
                );
            }) as typeof fs.statSync;
            try {
                const acquired = await acquireVenvLock(lockPath, {
                    maxWaitMs,
                    pollIntervalMs: 20,
                    staleMs: 10_000,
                });
                const elapsed = Date.now() - start;
                assert.strictEqual(acquired, false);
                assert.ok(
                    elapsed < maxWaitMs + 250,
                    `expected a bounded wait (~${maxWaitMs}ms), took ${elapsed}ms`
                );
            } finally {
                mutableFs.statSync = origStatSync;
            }
        });
    });
});
