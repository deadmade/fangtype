import { EventEmitter, extensions } from 'vscode';
import type { Disposable, Event, Uri } from 'vscode';
import { PythonExtension } from '@vscode/python-extension';
import { traceError, traceLog } from './log/logging';

/** The Python extension id whose API resolves the active interpreter. */
const PYTHON_EXTENSION_ID = 'ms-python.python';

/** Interpreter details; argv-style `path` allows wrappers, `undefined` → use the setting/env. */
export interface IInterpreterDetails {
    path?: string[];
    resource?: Uri;
}

const onDidChangePythonInterpreterEvent = new EventEmitter<IInterpreterDetails>();

/** Fires once at startup and again whenever the active interpreter changes. */
export const onDidChangePythonInterpreter: Event<IInterpreterDetails> =
    onDidChangePythonInterpreterEvent.event;

let pythonApi: PythonExtension | undefined;

/** Memoized Python API; `undefined` when `ms-python.python` is absent, so callers degrade. */
async function getPythonExtensionAPI(): Promise<PythonExtension | undefined> {
    if (pythonApi) {
        return pythonApi;
    }
    if (!extensions.getExtension(PYTHON_EXTENSION_ID)) {
        traceLog(
            `Python extension (${PYTHON_EXTENSION_ID}) is not installed; ` +
                'falling back to the configured interpreter / FANGTYPE_INTERPRETER.'
        );
        return undefined;
    }
    pythonApi = await PythonExtension.api();
    return pythonApi;
}

/**
 * Subscribe to interpreter changes and emit the initial interpreter once; a no-op when the Python
 * extension is absent.
 *
 * @param disposables - Subscriptions sink (usually `context.subscriptions`).
 */
export async function initializePython(disposables: Disposable[]): Promise<void> {
    try {
        const api = await getPythonExtensionAPI();
        if (!api) {
            // No interpreter to announce; the server launch resolves it from the setting / env.
            return;
        }

        disposables.push(
            api.environments.onDidChangeActiveEnvironmentPath(e => {
                // `e.resource` is dropped: the launch re-reads per-folder settings itself.
                onDidChangePythonInterpreterEvent.fire({ path: [e.path] });
            })
        );

        traceLog('Resolving the active interpreter from the Python extension.');
        onDidChangePythonInterpreterEvent.fire(await getInterpreterDetails());
    } catch (error) {
        traceError('Failed to initialize Python interpreter resolution: ', error);
    }
}

/**
 * Resolve the active interpreter's executable path for a resource.
 *
 * @param resource - Optional resource whose folder scope selects the interpreter.
 * @returns Details with `path` set to `[executable]`, or `path` `undefined` when
 *   no interpreter could be resolved.
 */
export async function getInterpreterDetails(resource?: Uri): Promise<IInterpreterDetails> {
    const api = await getPythonExtensionAPI();
    if (!api) {
        return { path: undefined, resource };
    }
    const environment = await api.environments.resolveEnvironment(
        api.environments.getActiveEnvironmentPath(resource)
    );
    const executable = environment?.executable.uri?.fsPath;
    if (executable) {
        return { path: [executable], resource };
    }
    return { path: undefined, resource };
}
