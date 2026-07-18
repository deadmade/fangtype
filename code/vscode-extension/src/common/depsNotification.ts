import { commands, env, window } from 'vscode';
import { BUNDLED_REQUIREMENTS_PATH } from './constants';

/** POSIX single-quoting: nothing but `'` is special inside `'...'`, and that ends the quote. */
function quotePosix(arg: string): string {
    return `'${arg.replaceAll("'", `'\\''`)}'`;
}

/** PowerShell single-quoting: `'` is escaped by doubling it. */
function quotePwsh(arg: string): string {
    return `'${arg.replaceAll("'", "''")}'`;
}

/** Build the pip install argv; spawned without a shell, so no quoting applies. */
export function buildInstallArgv(interpreterArgv: string[], requirementsPath: string): string[] {
    return [...interpreterArgv.slice(1), '-m', 'pip', 'install', '-r', requirementsPath];
}

/**
 * Render the install command for humans (dialog text, clipboard) — never executed by us.
 * Every argument is quoted: `fangtype.interpreter` is workspace-settable, so a cloned repo
 * controls these strings and a pasted command is still an exec path. PowerShell needs a
 * leading `&` to run a quoted exe path.
 */
export function buildInstallCommand(
    interpreterArgv: string[],
    requirementsPath: string,
    platform: NodeJS.Platform = process.platform
): string {
    const pwsh = platform === 'win32';
    const quote = pwsh ? quotePwsh : quotePosix;
    const argv = [interpreterArgv[0] ?? '', ...buildInstallArgv(interpreterArgv, requirementsPath)];
    const base = argv.map(quote).join(' ');
    return pwsh ? `& ${base}` : base;
}

/** Offer to install missing server deps; runs in a visible terminal, never silently. */
export function promptInstallDeps(interpreterArgv: string[], missing: string[]): void {
    if (interpreterArgv.length === 0) {
        return;
    }
    const command = buildInstallCommand(interpreterArgv, BUNDLED_REQUIREMENTS_PATH);
    const detail = missing.length ? ` (missing: ${missing.join(', ')})` : '';
    void window
        .showErrorMessage(
            `Fangtype: the selected Python interpreter is missing the server's ` +
                `dependencies${detail}.\n\nWill run:  ${command}\n\n` +
                `Install them into that interpreter?`,
            'Install dependencies',
            'Copy command',
            'Open Settings'
        )
        .then(choice => {
            if (choice === 'Install dependencies') {
                // shellPath/shellArgs runs the interpreter directly as argv — no shell parses
                // this, so a metacharacter in `fangtype.interpreter` cannot become a command.
                const terminal = window.createTerminal({
                    name: 'Fangtype: install deps',
                    shellPath: interpreterArgv[0],
                    shellArgs: buildInstallArgv(interpreterArgv, BUNDLED_REQUIREMENTS_PATH),
                });
                terminal.show();
            } else if (choice === 'Copy command') {
                void env.clipboard.writeText(command);
                void window.showInformationMessage('Fangtype: install command copied.');
            } else if (choice === 'Open Settings') {
                commands.executeCommand('workbench.action.openSettings', 'fangtype.interpreter');
            }
        });
}
