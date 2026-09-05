// The `vscode` module is injected by the Electron host and cannot be resolved under plain
// node. These tests cover pure functions whose modules import `vscode` at top level but never
// call it, so an empty surface is enough to let the imports resolve.
//
// The classes below must be real constructors: `vscode-languageclient` subclasses them at
// module load. They must also be own enumerable properties rather than lazily minted by a
// Proxy, because TypeScript's `__importStar` copies own keys eagerly. Refresh the list with:
//   grep -rhoE 'extends [A-Za-z_$][A-Za-z0-9_$]*\.[A-Za-z]+' node_modules/vscode-languageclient/lib/
// dropping languageclient's own base classes (BaseLanguageClient, *Feature).
const Module = require('node:module');

const stub = {
    window: {},
    workspace: {},
    commands: {},
    env: {},
    extensions: {},
    ProgressLocation: {},
    Uri: {},
};

for (const name of [
    // `python.ts` constructs one at module load.
    'EventEmitter',
    'CallHierarchyItem',
    'CancellationError',
    'CodeAction',
    'CodeLens',
    'CompletionItem',
    'Diagnostic',
    'DocumentLink',
    'InlayHint',
    'SymbolInformation',
    'TypeHierarchyItem',
]) {
    stub[name] = class {};
}

// requestTimeout.ts (S6.4) actually calls cancel()/dispose() and reads token.isCancellationRequested,
// so this one needs real behaviour rather than an inert `class {}`.
stub.CancellationTokenSource = class {
    constructor() {
        this.token = {
            isCancellationRequested: false,
            onCancellationRequested: () => ({ dispose() {} }),
        };
    }
    cancel() {
        this.token.isCancellationRequested = true;
    }
    dispose() {}
};

const stubModule = new Module('vscode');
stubModule.exports = stub;
stubModule.loaded = true;
require.cache.vscode = stubModule;

const resolveFilename = Module._resolveFilename;
Module._resolveFilename = function (request, ...rest) {
    return request === 'vscode' ? 'vscode' : resolveFilename.call(this, request, ...rest);
};
