import * as path from 'path';

/** Client/output-channel/command id; matches the server's LSP name and `fangtype.*` settings. */
export const SERVER_ID = 'fangtype';

/** Human-readable server/display name shown in the UI. */
export const SERVER_NAME = 'Fangtype';

/** Extension root: the entrypoint is emitted to `dist/`, so one level above this module. */
export const EXTENSION_ROOT_DIR = path.dirname(__dirname);

/** Directory holding the bundled Python server sources (launched in Phase 2). */
export const BUNDLED_TOOL_DIR = path.join(EXTENSION_ROOT_DIR, 'bundled', 'tool');

/** Directory holding the bundled third-party Python libraries. */
export const BUNDLED_LIBS_DIR = path.join(EXTENSION_ROOT_DIR, 'bundled', 'libs');

/** Absolute path to the server entrypoint run under the user's interpreter. */
export const SERVER_SCRIPT_PATH = path.join(BUNDLED_TOOL_DIR, 'lsp_server.py');

/** Debug entrypoint, used only when `DEBUG_FANGTYPE` is set; starts a `debugpy` listener first. */
export const SERVER_DEBUG_SCRIPT_PATH = path.join(BUNDLED_TOOL_DIR, 'lsp_runner.py');

/** Absolute path to the dependency preflight probe run before server start. */
export const PREFLIGHT_SCRIPT_PATH = path.join(BUNDLED_TOOL_DIR, 'preflight.py');

/** Absolute path to the shipped hash-pinned dependency lockfile. */
export const BUNDLED_REQUIREMENTS_PATH = path.join(
    EXTENSION_ROOT_DIR,
    'bundled',
    'requirements.txt'
);
