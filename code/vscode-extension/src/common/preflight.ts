import { spawn } from 'child_process';
import { PREFLIGHT_SCRIPT_PATH } from './constants';
import { traceError, traceInfo } from './log/logging';

export type PreflightResult = { ok: true } | { ok: false; missing: string[] };

/** Pure parse of the probe's stdout + exit code into a result. */
export function parsePreflight(stdout: string, code: number): PreflightResult {
    if (code === 0) {
        return { ok: true };
    }
    const missing = stdout
        .split(',')
        .map(s => s.trim())
        .filter(Boolean);
    return { ok: false, missing };
}

/**
 * Pure: classify a close event into a result. Per the probe contract, a nonzero exit with
 * empty stdout is a crash (not a real missing-deps report), and a signal-killed process
 * (code === null) can't tell us anything about deps either — both fail open.
 */
export function classifyClose(
    stdout: string,
    code: number | null,
    signal: NodeJS.Signals | null
): PreflightResult {
    if (signal !== null || code === null) {
        return { ok: true };
    }
    const result = parsePreflight(stdout, code);
    if (!result.ok && result.missing.length === 0) {
        return { ok: true };
    }
    return result;
}

/** Preflight under the real launch interpreter+env; if it can't run → ok, don't blame deps. */
export async function checkServerDeps(
    interpreterArgv: string[],
    env: Record<string, string>
): Promise<PreflightResult> {
    if (interpreterArgv.length === 0) {
        return { ok: true };
    }
    const [command, ...leading] = interpreterArgv;
    if (!command) {
        return { ok: true };
    }
    return new Promise<PreflightResult>(resolve => {
        let stdout = '';
        let stderr = '';
        let settled = false;
        const done = (r: PreflightResult) => {
            if (!settled) {
                settled = true;
                resolve(r);
            }
        };
        try {
            const child = spawn(command, [...leading, PREFLIGHT_SCRIPT_PATH], {
                env: { ...process.env, ...env },
            });
            child.stdout.on('data', (d: Buffer) => (stdout += d.toString()));
            child.stderr.on('data', (d: Buffer) => (stderr += d.toString()));
            child.on('error', err => {
                traceError(`Dependency preflight could not run: ${err}`);
                done({ ok: true }); // can't classify → don't block launch
            });
            child.on('close', (code, signal) => {
                const result = classifyClose(stdout, code, signal);
                if (signal !== null) {
                    traceError(`Dependency preflight was killed by signal ${signal}`);
                } else if (result.ok && code !== 0) {
                    traceError(`Dependency preflight crashed (exit ${code}): ${stderr}`);
                } else if (!result.ok) {
                    traceInfo(`Preflight: missing deps ${result.missing.join(', ')}`);
                }
                done(result);
            });
        } catch (err) {
            traceError(`Dependency preflight threw: ${err}`);
            done({ ok: true });
        }
    });
}
