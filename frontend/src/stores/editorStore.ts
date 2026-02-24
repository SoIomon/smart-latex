import { create } from 'zustand';
import type { EditorView } from '@codemirror/view';
import type { CompileResult } from '../types';

export type EditorMode = 'edit' | 'preview' | 'split';
export type SyncSource = 'editor' | 'pdf' | null;

interface EditorState {
  latexContent: string;
  editorMode: EditorMode;
  compiling: boolean;
  compileResult: CompileResult | null;
  pdfUrl: string | null;
  isGenerating: boolean;
  compileErrors: string[];
  compileLog: string;

  // SyncTeX state
  editorView: EditorView | null;
  syncTargetPage: number | null;
  syncTargetY: number | null;
  syncTargetLine: number | null;
  lineMap: Record<string, { page: number; y: number }> | null;
  syncSource: SyncSource;

  setLatexContent: (content: string) => void;
  setEditorMode: (mode: EditorMode) => void;
  setCompiling: (compiling: boolean) => void;
  setCompileResult: (result: CompileResult | null) => void;
  setPdfUrl: (url: string | null) => void;
  setIsGenerating: (generating: boolean) => void;
  setCompileErrors: (errors: string[]) => void;
  setCompileLog: (log: string) => void;

  // SyncTeX actions
  setEditorView: (view: EditorView | null) => void;
  setSyncTarget: (page: number | null, y: number | null) => void;
  setSyncTargetLine: (line: number | null) => void;
  setLineMap: (map: Record<string, { page: number; y: number }> | null) => void;
  setSyncSource: (source: SyncSource) => void;
}

let syncSourceTimer: ReturnType<typeof setTimeout> | null = null;

export const useEditorStore = create<EditorState>((set) => ({
  latexContent: '',
  editorMode: 'edit',
  compiling: false,
  compileResult: null,
  pdfUrl: null,
  isGenerating: false,
  compileErrors: [],
  compileLog: '',

  // SyncTeX state
  editorView: null,
  syncTargetPage: null,
  syncTargetY: null,
  syncTargetLine: null,
  lineMap: null,
  syncSource: null,

  setLatexContent: (content) => set({ latexContent: content }),
  setEditorMode: (mode) => set({ editorMode: mode }),
  setCompiling: (compiling) => set({ compiling }),
  setCompileResult: (result) => set({ compileResult: result }),
  setPdfUrl: (url) => set({ pdfUrl: url }),
  setIsGenerating: (generating) => set({ isGenerating: generating }),
  setCompileErrors: (errors) => set({ compileErrors: errors }),
  setCompileLog: (log) => set({ compileLog: log }),

  // SyncTeX actions
  setEditorView: (view) => set({ editorView: view }),
  setSyncTarget: (page, y) => set({ syncTargetPage: page, syncTargetY: y }),
  setSyncTargetLine: (line) => set({ syncTargetLine: line }),
  setLineMap: (map) => set({ lineMap: map }),
  setSyncSource: (source) => {
    if (syncSourceTimer) clearTimeout(syncSourceTimer);
    set({ syncSource: source });
    if (source !== null) {
      syncSourceTimer = setTimeout(() => {
        set({ syncSource: null });
        syncSourceTimer = null;
      }, 200);
    }
  },
}));
