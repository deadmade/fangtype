export interface LspTextEdit {
    range: {
        start: { line: number; character: number };
        end: { line: number; character: number };
    };
    newText: string;
}

export interface LspVersionedTextDocumentEdit {
    textDocument: { uri: string; version: number | null };
    edits: LspTextEdit[];
}

export interface LspWorkspaceEdit {
    // Legacy unversioned form; kept for back-compat.
    changes?: Record<string, LspTextEdit[]>;
    // Versioned form: each edit carries its version, so a stale full-document replace is rejected.
    documentChanges?: LspVersionedTextDocumentEdit[];
}

export interface FangtypeResult {
    success: boolean;
    message?: string;
    edits?: LspWorkspaceEdit;
    inserted_count?: number;
    removed_count?: number;
    // Why each variable was (not) annotated ("selected" | "all_mypy_invalid"); benchmark-only.
    variable_drop_reasons?: Record<string, number>;
}

export interface PreviewItem {
    variable: string;
    type: string;
    line?: number;
}

export interface PreviewResult {
    success: boolean;
    message?: string;
    total_changes: number;
    will_insert?: PreviewItem[];
    will_skip?: PreviewItem[];
    will_remove?: PreviewItem[];
}
