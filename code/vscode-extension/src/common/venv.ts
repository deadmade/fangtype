import { spawn } from 'child_process';
import { createHash } from 'crypto';
import * as fs from 'fs';
import * as path from 'path';
import { commands, env, ProgressLocation, window, workspace } from 'vscode';
import { BUNDLED_REQUIREMENTS_PATH } from './constants';
import { traceError, traceInfo } from './log/logging';

/** Managed venv in globalStorage, not the user's env; keyed by base CPython minor (wheel ABI). */

/** Bumped when the stamp shape changes so old venvs are rebuilt rather than misread. */
export const VENV_STAMP_SCHEMA_VERSION = 1;

/** Marker written (last, atomically) into a built venv to record what produced it. */
export interface IVenvStamp {
    schemaVersion: number;
    /** Base interpreter the venv was created from. */
    basePython: string;
    /** Full base version, e.g. `3.12.4`. */
    pythonVersion: string;
    /** Base minor, e.g. `3.12` — the ABI key. */
    pythonVersionMinor: string;
    /** `sha256:...` of the requirements file the venv was installed from. */
    requirementsHash: string;
    createdAt: string;
}

/** Resolved on-disk locations for a versioned managed venv. */
export interface IVenvPaths {
    venvDir: string;
    pythonExe: string;
    stampFile: string;
}

/** How a venv build failed, so the UI can offer the right remedy. */
export type VenvBuildErrorKind =
    | 'missing-venv-module'
    | 'network'
    | 'no-base-interpreter'
    | 'probe-failed'
    | 'unknown';

/** A build failure carrying its classified `kind` (see {@link VenvBuildErrorKind}). */
export class VenvError extends Error {
    constructor(
        public readonly kind: VenvBuildErrorKind,
        message: string
    ) {
        super(message);
        this.name = 'VenvError';
    }
}

// ---- Pure helpers (unit-tested) -------------------------------------------

/** Venv layout under `globalStorage`; `platform` is injectable so tests assert win32 on posix. */
export function buildVenvPaths(
    globalStorage: string,
    pyVersionMinor: string,
    platform: NodeJS.Platform = process.platform
): IVenvPaths {
    const p = platform === 'win32' ? path.win32 : path.posix;
    const venvDir = p.join(globalStorage, 'venvs', `py${pyVersionMinor}`);
    const pythonExe =
        platform === 'win32'
            ? p.join(venvDir, 'Scripts', 'python.exe')
            : p.join(venvDir, 'bin', 'python');
    const stampFile = p.join(venvDir, '.fangtype-venv.json');
    return { venvDir, pythonExe, stampFile };
}

/** Rebuild on missing/invalid stamp, schema bump, different base minor (ABI), or changed pins. */
export function venvNeedsRebuild(
    stamp: IVenvStamp | null,
    pyVersionMinor: string,
    reqHash: string
): boolean {
    if (!stamp) {
        return true;
    }
    if (stamp.schemaVersion !== VENV_STAMP_SCHEMA_VERSION) {
        return true;
    }
    if (stamp.pythonVersionMinor !== pyVersionMinor) {
        return true;
    }
    if (stamp.requirementsHash !== reqHash) {
        return true;
    }
    return false;
}

/** argv to create the venv: `<basePython...> -m venv <venvDir>`. */
export function buildVenvCreateArgv(basePython: string[], venvDir: string): string[] {
    return [...basePython, '-m', 'venv', venvDir];
}

/** argv to pip-install the deps; spawned without a shell, so no quoting/PowerShell quirks apply. */
export function buildVenvInstallArgv(venvPython: string, requirementsPath: string): string[] {
    return [venvPython, '-m', 'pip', 'install', '-r', requirementsPath];
}

/** Classify a create/install failure from its stderr so the UI can suggest a fix. */
export function parseVenvBuildError(stderr: string): VenvBuildErrorKind {
    const s = stderr.toLowerCase();
    if (
        s.includes('ensurepip is not available') ||
        s.includes('no module named venv') ||
        s.includes('the virtual environment was not created successfully') ||
        s.includes('python3-venv')
    ) {
        return 'missing-venv-module';
    }
    const timedOut = s.includes('connection') && s.includes('timed out');
    if (
        timedOut ||
        s.includes('could not find a version') ||
        s.includes('temporary failure in name resolution') ||
        s.includes('network is unreachable') ||
        s.includes('failed to establish a new connection') ||
        s.includes('max retries exceeded')
    ) {
        return 'network';
    }
    return 'unknown';
}

/** `sha256:<hex>` of the requirements contents; guards the direct pins against drift. */
export function computeRequirementsHash(contents: string): string {
    return `sha256:${createHash('sha256').update(contents, 'utf8').digest('hex')}`;
}

/** Parse a base interpreter's `major.minor.micro` probe output into full + minor version. */
export function parseInterpreterVersion(stdout: string): { full: string; minor: string } | null {
    const m = stdout.trim().match(/^(\d+)\.(\d+)\.(\d+)$/);
    if (!m) {
        return null;
    }
    return { full: `${m[1]}.${m[2]}.${m[3]}`, minor: `${m[1]}.${m[2]}` };
}

// ---- Impure I/O (integration-tested) --------------------------------------

/** Result of a captured subprocess run. */
export interface ICaptureResult {
    code: number;
    stdout: string;
    stderr: string;
}

/**
 * Map a `close` event to our exit-code contract: a real code passes through; a signal-killed
 * child (`code === null`, `signal` set) is a failure (`-1`), never a false success — a
 * `venv`/`pip install` killed mid-run must not make `buildVenv` stamp a half-built venv.
 */
export function closeCodeFor(code: number | null, signal: NodeJS.Signals | null): number {
    return code ?? (signal ? -1 : 0);
}

/** Spawn `argv` and capture output; never rejects — a spawn error resolves `code: -1` + stderr. */
export function runCapture(
    argv: string[],
    opts: { cwd?: string; env?: Record<string, string> } = {}
): Promise<ICaptureResult> {
    const [command, ...args] = argv;
    if (!command) {
        return Promise.resolve({ code: -1, stdout: '', stderr: 'no command to run' });
    }
    return new Promise<ICaptureResult>(resolve => {
        let stdout = '';
        let stderr = '';
        let settled = false;
        const done = (r: ICaptureResult) => {
            if (!settled) {
                settled = true;
                resolve(r);
            }
        };
        try {
            const child = spawn(command, args, {
                cwd: opts.cwd,
                env: opts.env ? { ...process.env, ...opts.env } : process.env,
            });
            child.stdout.on('data', (d: Buffer) => (stdout += d.toString()));
            child.stderr.on('data', (d: Buffer) => (stderr += d.toString()));
            child.on('error', err => done({ code: -1, stdout, stderr: `${stderr}${err}` }));
            child.on('close', (code, signal) =>
                done({ code: closeCodeFor(code, signal), stdout, stderr })
            );
        } catch (err) {
            done({ code: -1, stdout, stderr: String(err) });
        }
    });
}

/** Read + JSON-parse the stamp; returns `null` on any read/parse error. */
export function readStamp(stampFile: string): IVenvStamp | null {
    try {
        const parsed: unknown = JSON.parse(fs.readFileSync(stampFile, 'utf8'));
        if (parsed && typeof parsed === 'object') {
            return parsed as IVenvStamp;
        }
        return null;
    } catch {
        return null;
    }
}

/** Write the stamp last and atomically (temp + rename) so a half-built venv never looks valid. */
function writeStampAtomic(stampFile: string, stamp: IVenvStamp): void {
    const tmp = `${stampFile}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(stamp, null, 2), 'utf8');
    fs.renameSync(tmp, stampFile);
}

/** Probe the base interpreter for its version; throws `VenvError('probe-failed')` if it can't. */
async function probeInterpreterVersion(
    basePython: string[]
): Promise<{ full: string; minor: string }> {
    const argv = [...basePython, '-c', 'import sys;print("%d.%d.%d" % sys.version_info[:3])'];
    const res = await runCapture(argv);
    const parsed = res.code === 0 ? parseInterpreterVersion(res.stdout) : null;
    if (!parsed) {
        throw new VenvError(
            'probe-failed',
            `Could not determine the Python version of ${basePython[0]}: ${res.stderr || res.stdout}`
        );
    }
    return parsed;
}

/** In-process guard so two windows/activations don't build the same venv concurrently. */
const inflight = new Map<string, Promise<string>>();

// ---- Cross-process lock (M8/M9) --------------------------------------------
// `inflight` above only guards this process; the managed venv under globalStorage is shared
// by every VS Code window (each a separate extension-host process). Two windows racing
// `buildVenv`/`removeVenv` both `fs.rmSync` the same venv dir while the other reads/imports
// from it. POSIX `rename` cannot atomically replace a non-empty directory, so instead of a
// rename-swap we take a cross-process lock around the critical section and never delete a
// venv whose stamp is currently valid.

/** How long a fresh-looking lock is trusted before we assume its holder crashed and reclaim it. */
const LOCK_STALE_MS = 10 * 60 * 1000;
/** How long `acquireVenvLock` waits for a genuinely live holder before giving up. */
const LOCK_MAX_WAIT_MS = 120_000;
const LOCK_POLL_INTERVAL_MS = 500;

export interface IVenvLockOptions {
    maxWaitMs?: number;
    pollIntervalMs?: number;
    staleMs?: number;
}

/** A lockfile older than `staleMs` is presumed abandoned by a crashed/killed holder. */
export function isStaleLock(mtimeMs: number, nowMs: number, staleMs: number): boolean {
    return nowMs - mtimeMs > staleMs;
}

/** Atomically create `lockPath` (`O_EXCL`); `false` on `EEXIST` (another process holds it). */
export function tryAcquireLockSync(lockPath: string): boolean {
    let fd: number;
    try {
        fd = fs.openSync(lockPath, 'wx');
    } catch (err) {
        if ((err as NodeJS.ErrnoException).code === 'EEXIST') {
            return false;
        }
        throw err;
    }
    try {
        fs.writeSync(fd, String(process.pid));
        fs.closeSync(fd);
    } catch (err) {
        // Partial write (e.g. disk full): don't leak the fd or leave an orphan lockfile that
        // would wedge every future acquire until the stale-reclaim window passes.
        try {
            fs.closeSync(fd);
        } catch {
            // already closed
        }
        try {
            fs.unlinkSync(lockPath);
        } catch {
            // already gone
        }
        throw err;
    }
    return true;
}

/** Release a held lock; a no-op if it's already gone. */
export function releaseLockSync(lockPath: string): void {
    fs.rmSync(lockPath, { force: true });
}

/**
 * Cross-process lock for the venv build/remove critical section. Tries an atomic create;
 * if another process holds it, reclaims it when stale (crashed holder) or else polls up to
 * `maxWaitMs` before giving up. Callers must release in a `finally`.
 */
export async function acquireVenvLock(
    lockPath: string,
    opts: IVenvLockOptions = {}
): Promise<boolean> {
    const maxWaitMs = opts.maxWaitMs ?? LOCK_MAX_WAIT_MS;
    const pollIntervalMs = opts.pollIntervalMs ?? LOCK_POLL_INTERVAL_MS;
    const staleMs = opts.staleMs ?? LOCK_STALE_MS;
    const deadline = Date.now() + maxWaitMs;

    for (;;) {
        // Checked first on every iteration (including both `continue` paths below) so
        // pathological lock churn (repeated EEXIST-then-stat-ENOENT) can't busy-loop past
        // maxWaitMs — see ponytail-debt review of Task 5.
        if (Date.now() >= deadline) {
            return false;
        }
        if (tryAcquireLockSync(lockPath)) {
            return true;
        }
        try {
            const stat = fs.statSync(lockPath);
            if (isStaleLock(stat.mtimeMs, Date.now(), staleMs)) {
                // ponytail: reclaiming a stale lock races a holder that is still alive but has
                // been building for >staleMs (10min, far beyond a normal venv build) — the
                // accepted residual is two concurrent rebuilds of the same venv dir in that
                // pathologically-slow case. Upgrade path if this ever bites: have the holder
                // periodically touch() the lock while it works, and only reclaim on top of that.
                releaseLockSync(lockPath);
                continue;
            }
        } catch {
            continue; // lock vanished between the failed acquire and the stat; retry
        }
        await new Promise(resolve => setTimeout(resolve, pollIntervalMs));
    }
}

function venvLockPath(venvDir: string): string {
    return `${venvDir}.lock`;
}

/** Return the managed venv's python; rebuild when stale, stamp last. Throws {@link VenvError}. */
export async function ensureVenv(
    globalStoragePath: string,
    baseInterpreter: string[],
    reportProgress = true
): Promise<string> {
    if (baseInterpreter.length === 0) {
        throw new VenvError(
            'no-base-interpreter',
            'No base interpreter to build a virtualenv from.'
        );
    }

    const version = await probeInterpreterVersion(baseInterpreter);
    const reqHash = computeRequirementsHash(fs.readFileSync(BUNDLED_REQUIREMENTS_PATH, 'utf8'));
    const paths = buildVenvPaths(globalStoragePath, version.minor);

    if (
        !venvNeedsRebuild(readStamp(paths.stampFile), version.minor, reqHash) &&
        fs.existsSync(paths.pythonExe)
    ) {
        traceInfo(`Fangtype: reusing managed venv at ${paths.venvDir}`);
        return paths.pythonExe;
    }

    let build = inflight.get(paths.venvDir);
    if (!build) {
        build = buildVenv(baseInterpreter, paths, version, reqHash, reportProgress).finally(() =>
            inflight.delete(paths.venvDir)
        );
        inflight.set(paths.venvDir, build);
    }
    return build;
}

/** Remove any stale venv dir, create the venv, install deps, then stamp it. */
async function buildVenv(
    baseInterpreter: string[],
    paths: IVenvPaths,
    version: { full: string; minor: string },
    reqHash: string,
    reportProgress: boolean
): Promise<string> {
    const run = async (report: (message: string) => void): Promise<string> => {
        const isNowValid = (): boolean =>
            !venvNeedsRebuild(readStamp(paths.stampFile), version.minor, reqHash) &&
            fs.existsSync(paths.pythonExe);

        // The lockfile is a sibling of venvDir, so its parent must exist before we can even
        // attempt the O_EXCL create (on a fresh install, `venvs/` doesn't exist yet — without
        // this, the open would fail ENOENT rather than the EEXIST we handle below).
        fs.mkdirSync(path.dirname(paths.venvDir), { recursive: true });
        const lockPath = venvLockPath(paths.venvDir);
        const acquired = await acquireVenvLock(lockPath);
        if (!acquired) {
            // Another window is (or was, until just now) building/removing this same venv.
            // Never rmSync out from under it — if it finished and left a valid venv, reuse it.
            if (isNowValid()) {
                traceInfo(`Fangtype: reusing venv built by another window at ${paths.venvDir}`);
                return paths.pythonExe;
            }
            throw new VenvError(
                'unknown',
                `Timed out waiting for another Fangtype window to finish building ${paths.venvDir}.`
            );
        }
        try {
            // Re-check now that we hold the lock: a peer may have finished a valid rebuild in
            // the gap between our pre-lock check and acquiring it. Rebuilding anyway would
            // rmSync a venv that peer (or its server) may already be using.
            if (isNowValid()) {
                traceInfo(
                    `Fangtype: venv at ${paths.venvDir} is already up to date; skipping rebuild`
                );
                return paths.pythonExe;
            }
            report('Creating environment…');
            // ponytail: this lock guards concurrent BUILDERS, not IMPORTERS — a peer window's
            // already-running server that imported from venvDir can still be disrupted by this
            // rmSync. Upgrade path if this ever bites: build to a side dir and swap, or refuse
            // rebuild while a peer server is live.
            fs.rmSync(paths.venvDir, { recursive: true, force: true });

            const create = await runCapture(buildVenvCreateArgv(baseInterpreter, paths.venvDir));
            if (create.code !== 0) {
                traceError(`Fangtype venv create failed: ${create.stderr}`);
                throw new VenvError(
                    parseVenvBuildError(create.stderr),
                    create.stderr || 'venv creation failed'
                );
            }

            report('Installing server dependencies…');
            const install = await runCapture(
                buildVenvInstallArgv(paths.pythonExe, BUNDLED_REQUIREMENTS_PATH)
            );
            if (install.code !== 0) {
                traceError(`Fangtype venv install failed: ${install.stderr}`);
                throw new VenvError(
                    parseVenvBuildError(install.stderr),
                    install.stderr || 'dependency install failed'
                );
            }

            writeStampAtomic(paths.stampFile, {
                schemaVersion: VENV_STAMP_SCHEMA_VERSION,
                basePython: baseInterpreter[0] ?? '',
                pythonVersion: version.full,
                pythonVersionMinor: version.minor,
                requirementsHash: reqHash,
                createdAt: new Date().toISOString(),
            });
            traceInfo(`Fangtype: managed venv ready at ${paths.venvDir}`);
            return paths.pythonExe;
        } finally {
            releaseLockSync(lockPath);
        }
    };

    if (!reportProgress) {
        return run(message => traceInfo(`Fangtype: ${message}`));
    }
    return window.withProgress(
        { location: ProgressLocation.Notification, title: 'Fangtype', cancellable: false },
        progress => run(message => progress.report({ message }))
    );
}

/** Delete the versioned venv dir for `baseInterpreter`'s minor version (rebuild/recovery). */
export async function removeVenv(
    globalStoragePath: string,
    baseInterpreter: string[]
): Promise<void> {
    if (baseInterpreter.length === 0) {
        return;
    }
    const version = await probeInterpreterVersion(baseInterpreter);
    const { venvDir } = buildVenvPaths(globalStoragePath, version.minor);
    // Same as buildVenv: the lockfile's parent must exist before O_EXCL-creating it, even if
    // the venv itself was never built (e.g. rebuild clicked before any build ever ran).
    fs.mkdirSync(path.dirname(venvDir), { recursive: true });
    const lockPath = venvLockPath(venvDir);
    const acquired = await acquireVenvLock(lockPath);
    if (!acquired) {
        // Explicit user action (rebuildEnvironment), but another window is mid-build/remove on
        // this same venv — skip rather than rmSync a dir it may be actively writing to.
        traceError(`Fangtype: could not remove ${venvDir}, another window is using it`);
        return;
    }
    try {
        // ponytail: same residual as buildVenv's rmSync — this lock guards BUILDERS, not
        // IMPORTERS, so a peer window's already-running server can still be disrupted here.
        fs.rmSync(venvDir, { recursive: true, force: true });
        traceInfo(`Fangtype: removed managed venv at ${venvDir}`);
    } finally {
        releaseLockSync(lockPath);
    }
}

/** Surface a build failure with its remedy: apt hint + `fromEnvironment` switch if no `venv`. */
export function promptVenvError(error: VenvError): void {
    if (error.kind === 'missing-venv-module') {
        const apt = 'sudo apt install python3-venv';
        void window
            .showErrorMessage(
                'Fangtype: the selected Python is missing the `venv` module, so the managed ' +
                    `environment could not be created. Install it (e.g. \`${apt}\`) or switch ` +
                    'Fangtype to use the current interpreter instead.',
                'Copy apt command',
                'Use current environment',
                'Open Settings'
            )
            .then(choice => {
                if (choice === 'Copy apt command') {
                    void env.clipboard.writeText(apt);
                    void window.showInformationMessage('Fangtype: apt command copied.');
                } else if (choice === 'Use current environment') {
                    void switchToFromEnvironment();
                } else if (choice === 'Open Settings') {
                    void commands.executeCommand(
                        'workbench.action.openSettings',
                        'fangtype.installMode'
                    );
                }
            });
        return;
    }

    void window
        .showErrorMessage(
            `Fangtype: could not set up the managed Python environment. ${error.message}`,
            'Use current environment',
            'Open Settings'
        )
        .then(choice => {
            if (choice === 'Use current environment') {
                void switchToFromEnvironment();
            } else if (choice === 'Open Settings') {
                void commands.executeCommand(
                    'workbench.action.openSettings',
                    'fangtype.installMode'
                );
            }
        });
}

/** Flip `fangtype.installMode` to `fromEnvironment` for the workspace (or globally). */
async function switchToFromEnvironment(): Promise<void> {
    const config = workspace.getConfiguration('fangtype');
    const target = workspace.workspaceFolders?.length ? undefined : true; // undefined = workspace, true = global
    await config.update('installMode', 'fromEnvironment', target);
}
