export interface LspTextEdit {
    range: {
        start: { line: number; character: number };
        end: { line: number; character: number };
    };
    newText: string;
}

export interface LspWorkspaceEdit {
    changes?: Record<string, LspTextEdit[]>;
}

export interface AutoTypeResult {
    success: boolean;
    message?: string;
    edits?: LspWorkspaceEdit;
    inserted_count?: number;
    removed_count?: number;
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
