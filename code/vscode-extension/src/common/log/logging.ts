import * as util from 'util';
import type { Disposable, LogOutputChannel } from 'vscode';

type Arguments = unknown[];

let channel: LogOutputChannel | undefined;

/**
 * Register the `LogOutputChannel` the module-level trace helpers write to.
 *
 * @param logChannel - Channel created via `createOutputChannel(name, {log:true})`.
 * @returns A disposable that unregisters the channel.
 */
export function registerLogger(logChannel: LogOutputChannel): Disposable {
    channel = logChannel;
    return {
        dispose: () => {
            channel = undefined;
        },
    };
}

/** Log at the default (log) level. */
export function traceLog(...args: Arguments): void {
    channel?.appendLine(util.format(...args));
}

/** Log at the error level. */
export function traceError(...args: Arguments): void {
    channel?.error(util.format(...args));
}

/** Log at the info level. */
export function traceInfo(...args: Arguments): void {
    channel?.info(util.format(...args));
}
