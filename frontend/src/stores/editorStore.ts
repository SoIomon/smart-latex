import { create } from 'zustand';
import type { CompileResult } from '../types';

export type EditorMode = 'edit' | 'preview' | 'split';

interface EditorState {
  latexContent: string;
  editorMode: EditorMode;
  compiling: boolean;
  compileResult: CompileResult | null;
  pdfUrl: string | null;
  isGenerating: boolean;
  compileErrors: string[];
  compileLog: string;
  setLatexContent: (content: string) => void;
  setEditorMode: (mode: EditorMode) => void;
  setCompiling: (compiling: boolean) => void;
  setCompileResult: (result: CompileResult | null) => void;
  setPdfUrl: (url: string | null) => void;
  setIsGenerating: (generating: boolean) => void;
  setCompileErrors: (errors: string[]) => void;
  setCompileLog: (log: string) => void;
}

export const useEditorStore = create<EditorState>((set) => ({
  latexContent: '',
  editorMode: 'edit',
  compiling: false,
  compileResult: null,
  pdfUrl: null,
  isGenerating: false,
  compileErrors: [],
  compileLog: '',

  setLatexContent: (content) => set({ latexContent: content }),
  setEditorMode: (mode) => set({ editorMode: mode }),
  setCompiling: (compiling) => set({ compiling }),
  setCompileResult: (result) => set({ compileResult: result }),
  setPdfUrl: (url) => set({ pdfUrl: url }),
  setIsGenerating: (generating) => set({ isGenerating: generating }),
  setCompileErrors: (errors) => set({ compileErrors: errors }),
  setCompileLog: (log) => set({ compileLog: log }),
}));
