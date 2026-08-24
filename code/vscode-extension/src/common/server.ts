import * as path from 'path';
import { window, workspace } from 'vscode';
import type { LogOutputChannel } from 'vscode';
import { LanguageClient, Trace } from 'vscode-languageclient/node';
import type { LanguageClientOptions, ServerOptions } from 'vscode-languageclient/node';

import {
    BUNDLED_LIBS_DIR,
    BUNDLED_TOOL_DIR,
    SERVER_DEBUG_SCRIPT_PATH,
    SERVER_ID,
    SERVER_NAME,
    SERVER_SCRIPT_PATH,
} from './constants';
import { getExtensionSettings, getGlobalSettings } from './settings';
import type { ISettings } from './settings';
import { getInterpreterDetails } from './python';
import { traceError, traceInfo } from './log/logging';
import { createMiddleware } from '../lsp/middleware';
import { checkServerDeps } from './preflight';
import { promptInstallDeps } from './depsNotification';
import { ensureVenv, promptVenvError, VenvError } from './venv';

/** Absolute paths the launched bootstrap needs (injected for testability). */
export interface IServerPaths {
    /** `lsp_server.py` run under the interpreter. */
    serverScript: string;
    /** `lsp_runner.py` — the debug variant that starts a `debugpy` listener. */
    serverDebugScript: string;
    /** `bundled/libs` (third-party deps + the fangtype package). */
    bundledLibs: string;
    /** `bundled/tool` (the bootstrap scripts). */
    bundledTool: string;
}

/** A resolved server invocation: the command, its args, and env overrides. */
interface IServerInvocation {
    /** Executable to spawn; empty when no interpreter could be resolved. */
    command: string;
    args: string[];
    /** Env overrides layered over `process.env` by the language client. */
    env: Record<string, string>;
}

/** Normalize any value thrown by `ensureVenv` into a `VenvError` so its catch never rethrows. */
export function toVenvError(err: unknown): VenvError {
    return err instanceof VenvError ? err : new VenvError('unknown', String(err));
}

/**
 * Chain overlapping calls to `fn` through a single in-flight promise so they run one at a time
 * instead of interleaving (e.g. two concurrent server restarts both reading/writing the same
 * module-level client). `.catch(() => {})` keeps a failed run from wedging the chain for later
 * calls; each call's own returned promise still reflects that call's outcome.
 */
export function createSerialRunner(fn: () => Promise<void>): () => Promise<void> {
    let chain: Promise<void> = Promise.resolve();
    return (): Promise<void> => {
        // eslint-disable-next-line @typescript-eslint/no-empty-function
        chain = chain.catch(() => {}).then(fn);
        return chain;
    };
}

/** The default bundle paths, from `constants.ts`. */
const DEFAULT_PATHS: IServerPaths = {
    serverScript: SERVER_SCRIPT_PATH,
    serverDebugScript: SERVER_DEBUG_SCRIPT_PATH,
    bundledLibs: BUNDLED_LIBS_DIR,
    bundledTool: BUNDLED_TOOL_DIR,
};

/**
 * Compute the interpreter-based server invocation (pure, so unit-testable without the vscode API).
 *
 * Env carries `LS_IMPORT_STRATEGY`, forwarded `FANGTYPE_*` (engine defaults to `jedi`), and a
 * `PYTHONPATH` folding `bundledLibs` + `bundledTool` into the inherited value — `useBundled`
 * prepends them so the bundle wins, otherwise appends so the environment wins. A truthy
 * `parentEnv.DEBUG_FANGTYPE` runs `serverDebugScript` and forwards the
 * `DEBUG_FANGTYPE`/`_PORT`/`_WAIT` knobs for `debugpy`; the non-debug path is unchanged.
 *
 * @param settings - Resolved settings (interpreter already filled by the caller).
 * @param paths - Bundle paths (defaults to `constants.ts`).
 * @param parentEnv - Environment to forward from (defaults to `process.env`).
 * @returns The command/args/env to launch; `command` is `''` when unresolved.
 */
export function buildServerOptions(
    settings: ISettings,
    paths: IServerPaths = DEFAULT_PATHS,
    parentEnv: NodeJS.ProcessEnv = process.env
): IServerInvocation {
    const importStrategy = settings.installMode === 'useBundled' ? 'useBundled' : 'fromEnvironment';
    const debugEnabled = Boolean(parentEnv.DEBUG_FANGTYPE);

    // Winning source (bundled vs environment) must come first for the server and its children.
    const inherited = parentEnv.PYTHONPATH
        ? parentEnv.PYTHONPATH.split(path.delimiter).filter(Boolean)
        : [];
    const bundled = [paths.bundledLibs, paths.bundledTool];
    const pythonPath =
        importStrategy === 'useBundled' ? [...bundled, ...inherited] : [...inherited, ...bundled];

    const env: Record<string, string> = {};
    for (const [key, value] of Object.entries(parentEnv)) {
        if (key.startsWith('FANGTYPE_') && value !== undefined) {
            env[key] = value;
        }
    }
    if (!env.FANGTYPE_ENGINE) {
        env.FANGTYPE_ENGINE = 'jedi';
    }
    // Forward the debugpy knobs only when requested, so the normal launch env stays byte-identical.
    if (debugEnabled) {
        for (const key of ['DEBUG_FANGTYPE', 'DEBUG_FANGTYPE_PORT', 'DEBUG_FANGTYPE_WAIT']) {
            const value = parentEnv[key];
            if (value !== undefined) {
                env[key] = value;
            }
        }
    }
    env.LS_IMPORT_STRATEGY = importStrategy;
    env.PYTHONPATH = pythonPath.join(path.delimiter);

    // `<interpreter...> lsp_server.py` (or lsp_runner.py when debugging is requested).
    const command = settings.interpreter[0] ?? '';
    const serverScript = debugEnabled ? paths.serverDebugScript : paths.serverScript;
    const args = [...settings.interpreter.slice(1), serverScript];
    return { command, args, env };
}

/**
 * Resolve the interpreter argv, in precedence order: the `fangtype.interpreter` setting, the Python
 * extension's active interpreter, then `FANGTYPE_INTERPRETER` (escape hatch without `ms-python`).
 *
 * @param settings - Resolved settings for the launch scope.
 * @returns The interpreter argv (possibly empty).
 */
export async function resolveInterpreter(settings: ISettings): Promise<string[]> {
    if (settings.interpreter.length > 0) {
        return settings.interpreter;
    }
    const details = await getInterpreterDetails();
    if (details.path && details.path.length > 0) {
        return details.path;
    }
    const fromEnv = process.env.FANGTYPE_INTERPRETER;
    return fromEnv ? [fromEnv] : [];
}

/**
 * Whether an install mode has to probe the launch interpreter for the server's dependencies.
 *
 * Only `managed` may skip it, because it just installed them into a venv it built. `useBundled`
 * ships none of them: nox vendors the pure-Python fangtype package alone, with `--no-deps`, and
 * that is exactly what keeps the VSIX universal across OS and CPython minor version. So libcst
 * and mypy are resolved from the user's interpreter under `useBundled` just as they are under
 * `fromEnvironment`, and a missing one has to be reported rather than discovered at first use.
 *
 * @param installMode - The resolved `fangtype.installMode` setting.
 * @returns True when the deps probe must run before launch.
 */
export function needsDepsProbe(installMode: string): boolean {
    return installMode !== 'managed';
}

/**
 * Create (but do not start) a client launching the server from source under the resolved
 * interpreter; shows an error and returns `undefined` so the caller aborts without retrying.
 *
 * @param settings - Resolved settings for the launch scope.
 * @param channel - Log channel used for output, trace, and middleware.
 * @returns The unstarted client, or `undefined` when the launch cannot proceed.
 */
export async function createServer(
    settings: ISettings,
    channel: LogOutputChannel,
    globalStoragePath: string
): Promise<LanguageClient | undefined> {
    const managed = settings.installMode === 'managed';

    // Base interpreter: Jedi/mypy infer against it, managed venv builds from it, others launch it.
    const baseInterpreter = await resolveInterpreter(settings);
    if (baseInterpreter.length === 0) {
        traceError('No Python interpreter available to launch the Fangtype server.');
        void window.showErrorMessage(
            'Fangtype: no Python interpreter found. Select one via the Python extension ' +
                'or set `fangtype.interpreter`.'
        );
        return undefined;
    }

    // Managed mode: build/own a venv and launch the server from it (never the user's env).
    let launchInterpreter = baseInterpreter;
    if (managed) {
        try {
            launchInterpreter = [await ensureVenv(globalStoragePath, baseInterpreter)];
        } catch (err) {
            // Anything thrown here (VenvError or a plain fs error, e.g. ENOENT on a missing
            // requirements file) must degrade the activation gracefully, never crash it silently.
            const venvError = toVenvError(err);
            traceError(`Fangtype: managed environment setup failed: ${venvError.message}`);
            promptVenvError(venvError);
            return undefined;
        }
    }

    const resolved: ISettings = { ...settings, interpreter: launchInterpreter };
    const invocation = buildServerOptions(resolved);

    if (!invocation.command) {
        traceError('No Python interpreter available to launch the Fangtype server.');
        void window.showErrorMessage(
            'Fangtype: no Python interpreter found. Select one via the Python extension ' +
                'or set `fangtype.interpreter`.'
        );
        return undefined;
    }

    if (needsDepsProbe(settings.installMode)) {
        const deps = await checkServerDeps(resolved.interpreter, invocation.env);
        if (!deps.ok) {
            traceError(
                `Fangtype server dependencies missing in the interpreter: ${deps.missing.join(', ')}`
            );
            promptInstallDeps(resolved.interpreter, deps.missing);
            return undefined;
        }
    }

    traceInfo(`Launching Fangtype server: ${[invocation.command, ...invocation.args].join(' ')}`);

    const serverOptions: ServerOptions = {
        command: invocation.command,
        args: invocation.args,
        // The language client merges these over `process.env`, so overrides win.
        options: { cwd: settings.cwd || process.cwd(), env: invocation.env },
    };

    // Only a managed venv is a separate env; else leave empty to keep SameEnvironment behavior.
    const projectInterpreter = managed ? (baseInterpreter[0] ?? '') : '';
    const projectRoot = managed && settings.workspace ? settings.cwd : '';

    const clientOptions: LanguageClientOptions = {
        documentSelector: [{ scheme: 'file', language: 'python' }],
        synchronize: {
            // Watch Python files; configuration is now pushed (see below), not pulled.
            fileEvents: workspace.createFileSystemWatcher('**/*.py'),
        },
        middleware: createMiddleware(channel),
        outputChannel: channel,
        traceOutputChannel: channel,
        // Pushed at handshake (server never pulls); projectInterpreter/Root add project-awareness.
        initializationOptions: {
            settings: getExtensionSettings(SERVER_ID),
            globalSettings: getGlobalSettings(SERVER_ID),
            projectInterpreter,
            projectRoot,
        },
    };

    return new LanguageClient(SERVER_ID, SERVER_NAME, serverOptions, clientOptions);
}

/** Map `fangtype.logLevel` (replaced `fangtype.trace.server`) onto the JSON-RPC trace level. */
export function logLevelToTrace(logLevel: string): Trace {
    return logLevel === 'debug' ? Trace.Verbose : Trace.Off;
}

/**
 * Stop any existing client, then create and start a fresh one.
 *
 * @param settings - Resolved settings for the launch scope.
 * @param channel - Log channel used for output, trace, and middleware.
 * @param oldClient - The previous client to stop/dispose, if any.
 * @returns The started client, or `undefined` when the launch failed.
 */
export async function restartServer(
    settings: ISettings,
    channel: LogOutputChannel,
    globalStoragePath: string,
    oldClient?: LanguageClient
): Promise<LanguageClient | undefined> {
    if (oldClient) {
        traceInfo('Stopping the existing Fangtype server before restart.');
        try {
            await oldClient.stop();
        } catch (error) {
            traceError(`Error stopping the previous server (continuing): ${error}`);
        }
    }

    const client = await createServer(settings, channel, globalStoragePath);
    if (!client) {
        return undefined;
    }

    try {
        await client.start();
        // Drive JSON-RPC tracing off logLevel (replaces the old fangtype.trace.server setting).
        await client.setTrace(logLevelToTrace(settings.logLevel));
        traceInfo('Fangtype language server started successfully.');
        return client;
    } catch (error) {
        traceError(`Failed to start the Fangtype server: ${error}`);
        void window.showErrorMessage(`Fangtype: failed to start the language server. ${error}`);
        return undefined;
    }
}
