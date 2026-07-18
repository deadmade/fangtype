import { workspace } from 'vscode';
import type { ConfigurationChangeEvent, WorkspaceConfiguration, WorkspaceFolder } from 'vscode';

/** Settings for one scope: infra fields drive the server launch, domain fields are pushed to it. */
export interface ISettings {
    // Infra fields (server launch / environment).
    cwd: string;
    workspace: string;
    interpreter: string[];
    installMode: string;

    // Fangtype domain settings (camelCase; server snake-cases these keys).
    mypyEnabled: boolean;
    mypyInferenceValidationEnabled: boolean;
    diagnosticSeverity: string;
    crossFileContractsEnabled: boolean;
    logLevel: string;
}

/** Fallbacks when a key is in neither user config nor package.json; mirror server Settings. */
const DEFAULTS = {
    installMode: 'managed',
    mypyEnabled: true,
    // Mirrors package.json's declared default (authoritative).
    mypyInferenceValidationEnabled: false,
    crossFileContractsEnabled: true,
    logLevel: 'warning',
} as const;

/** Derive diagnosticSeverity from logLevel (no longer its own setting); server still reads it. */
function severityForLogLevel(logLevel: string): string {
    switch (logLevel) {
        case 'debug':
            return 'hint';
        case 'info':
            return 'information';
        case 'error':
        case 'critical':
            return 'error';
        default: // warning
            return 'information';
    }
}

/** Infra keys read from config that are not part of the domain settings. */
const INFRA_KEYS = ['interpreter', 'installMode'] as const;

/** Domain keys pushed to the server (camelCase, snake-cased server-side). */
const DOMAIN_KEYS = [
    'mypyEnabled',
    'mypyInferenceValidationEnabled',
    'crossFileContractsEnabled',
    'logLevel',
] as const;

function resolveSettings(
    config: WorkspaceConfiguration,
    cwd: string,
    workspace: string
): ISettings {
    return {
        cwd,
        workspace,
        interpreter: config.get<string[]>('interpreter') ?? [],
        installMode: config.get<string>('installMode') ?? DEFAULTS.installMode,

        mypyEnabled: config.get<boolean>('mypyEnabled') ?? DEFAULTS.mypyEnabled,
        mypyInferenceValidationEnabled:
            config.get<boolean>('mypyInferenceValidationEnabled') ??
            DEFAULTS.mypyInferenceValidationEnabled,
        // Derived from logLevel (its own setting was merged away), still pushed to the server.
        diagnosticSeverity: severityForLogLevel(
            config.get<string>('logLevel') ?? DEFAULTS.logLevel
        ),
        crossFileContractsEnabled:
            config.get<boolean>('crossFileContractsEnabled') ?? DEFAULTS.crossFileContractsEnabled,
        logLevel: config.get<string>('logLevel') ?? DEFAULTS.logLevel,
    };
}

/**
 * Resolve settings for a single workspace folder.
 *
 * @param namespace - Settings namespace (e.g. `fangtype`).
 * @param workspaceFolder - The folder to resolve settings for.
 * @returns The resolved settings for that folder.
 */
export function getWorkspaceSettings(
    namespace: string,
    workspaceFolder: WorkspaceFolder
): ISettings {
    const config = workspace.getConfiguration(namespace, workspaceFolder.uri);
    return resolveSettings(config, workspaceFolder.uri.fsPath, workspaceFolder.uri.toString());
}

/**
 * Resolve per-folder settings for every open workspace folder.
 *
 * @param namespace - Settings namespace (e.g. `fangtype`).
 * @returns One `ISettings` entry per workspace folder.
 */
export function getExtensionSettings(namespace: string): ISettings[] {
    return (workspace.workspaceFolders ?? []).map(folder =>
        getWorkspaceSettings(namespace, folder)
    );
}

/**
 * Resolve global (folder-independent) settings.
 *
 * @param namespace - Settings namespace (e.g. `fangtype`).
 * @returns The resolved global settings.
 */
export function getGlobalSettings(namespace: string): ISettings {
    const config = workspace.getConfiguration(namespace);
    return resolveSettings(config, process.cwd(), '');
}

/**
 * Check whether a configuration change touched any of this extension's settings.
 *
 * @param e - The configuration change event.
 * @param namespace - Settings namespace (e.g. `fangtype`).
 * @returns `true` when a relevant setting changed.
 */
export function checkIfConfigurationChanged(
    e: ConfigurationChangeEvent,
    namespace: string
): boolean {
    const keys = [...INFRA_KEYS, ...DOMAIN_KEYS];
    return keys.some(key => e.affectsConfiguration(`${namespace}.${key}`));
}

/**
 * Check whether a change touched an infra setting (read only at launch, so it needs a respawn).
 *
 * @param e - The configuration change event.
 * @param namespace - Settings namespace (e.g. `fangtype`).
 * @returns `true` when an infra setting changed.
 */
export function checkIfInfraConfigurationChanged(
    e: ConfigurationChangeEvent,
    namespace: string
): boolean {
    return INFRA_KEYS.some(key => e.affectsConfiguration(`${namespace}.${key}`));
}
