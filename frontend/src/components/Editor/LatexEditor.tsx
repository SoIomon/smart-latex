import { useEffect, useRef, useState, useCallback } from 'react';
import { EditorView, keymap, lineNumbers, highlightActiveLine, highlightActiveLineGutter } from '@codemirror/view';
import { EditorState, type ChangeSpec } from '@codemirror/state';
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands';
import { bracketMatching, foldGutter, indentOnInput, StreamLanguage } from '@codemirror/language';
import { searchKeymap, highlightSelectionMatches } from '@codemirror/search';
import { autocompletion } from '@codemirror/autocomplete';
import { stex } from '@codemirror/legacy-modes/mode/stex';
import SelectionToolbar from './SelectionToolbar';
import { Tooltip } from 'antd';
import { useEditorStore } from '../../stores/editorStore';

interface LatexEditorProps {
  value: string;
  onChange: (value: string) => void;
  onForwardSync?: (line: number, column: number) => void;
}

interface SelectionInfo {
  text: string;
  from: number;
  to: number;
  position: { top: number; left: number };
}

const _scrollState = { programmatic: false }; // flag to suppress scroll-triggered forward sync during scrollIntoView

// Simple diff: compute minimal changes between old and new text
function computeChanges(oldText: string, newText: string): ChangeSpec[] {
  // Find common prefix
  let prefixLen = 0;
  const minLen = Math.min(oldText.length, newText.length);
  while (prefixLen < minLen && oldText[prefixLen] === newText[prefixLen]) {
    prefixLen++;
  }

  // Find common suffix (not overlapping with prefix)
  let suffixLen = 0;
  while (
    suffixLen < minLen - prefixLen &&
    oldText[oldText.length - 1 - suffixLen] === newText[newText.length - 1 - suffixLen]
  ) {
    suffixLen++;
  }

  const from = prefixLen;
  const to = oldText.length - suffixLen;
  const insert = newText.slice(prefixLen, newText.length - suffixLen);

  if (from === to && insert === '') return [];
  return [{ from, to, insert }];
}

export default function LatexEditor({ value, onChange, onForwardSync }: LatexEditorProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<EditorView | null>(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const onForwardSyncRef = useRef(onForwardSync);
  onForwardSyncRef.current = onForwardSync;

  const [selectionInfo, setSelectionInfo] = useState<SelectionInfo | null>(null);
  const [toolbarVisible, setToolbarVisible] = useState(false);
  const [showSelectionHint, setShowSelectionHint] = useState(false);
  const selectionHintShownRef = useRef(false);
  const dblClickFiredRef = useRef(false);

  const handleCloseToolbar = useCallback(() => {
    setToolbarVisible(false);
    setSelectionInfo(null);
  }, []);

  const handleReplace = useCallback((from: number, to: number, newText: string) => {
    const view = viewRef.current;
    if (!view) return;
    view.dispatch({
      changes: { from, to, insert: newText },
    });
  }, []);

  useEffect(() => {
    if (!containerRef.current) return;

    const state = EditorState.create({
      doc: value,
      extensions: [
        lineNumbers(),
        highlightActiveLine(),
        highlightActiveLineGutter(),
        history(),
        foldGutter(),
        indentOnInput(),
        bracketMatching(),
        autocompletion(),
        highlightSelectionMatches(),
        StreamLanguage.define(stex),
        keymap.of([
          ...defaultKeymap,
          ...historyKeymap,
          ...searchKeymap,
          indentWithTab,
        ]),
        EditorView.domEventHandlers({
          dblclick: (event, view) => {
            const pos = view.posAtCoords({ x: event.clientX, y: event.clientY });
            if (pos !== null) {
              const line = view.state.doc.lineAt(pos);
              dblClickFiredRef.current = true;
              setTimeout(() => { dblClickFiredRef.current = false; }, 200);
              onForwardSyncRef.current?.(line.number, 0);
            }
            return false; // allow default word selection
          },
        }),
        EditorView.updateListener.of((update) => {
          if (update.docChanged) {
            onChangeRef.current(update.state.doc.toString());
          }
          // Detect selection changes — only show toolbar for drag selections, not double-click
          if (update.selectionSet || update.docChanged) {
            const { from, to } = update.state.selection.main;
            if (from !== to && !dblClickFiredRef.current) {
              const selectedText = update.state.sliceDoc(from, to);
              if (selectedText.trim().length > 0) {
                const coords = update.view.coordsAtPos(from);
                if (coords) {
                  const top = Math.max(coords.top - 44, 4);
                  const left = Math.max(Math.min(coords.left, window.innerWidth - 400), 10);
                  setSelectionInfo({
                    text: selectedText,
                    from,
                    to,
                    position: { top, left },
                  });
                  setToolbarVisible(true);

                  if (!selectionHintShownRef.current) {
                    selectionHintShownRef.current = true;
                    setShowSelectionHint(true);
                    setTimeout(() => setShowSelectionHint(false), 4000);
                  }
                }
              }
            }
          }
        }),
        EditorView.theme({
          '&': { height: '100%' },
          '.cm-scroller': { overflow: 'auto' },
          '.cm-content': { fontFamily: '"Fira Code", "Consolas", monospace', fontSize: '14px' },
          '.cm-gutters': { background: '#f8f8f8', borderRight: '1px solid #ddd' },
          '&.cm-editor.cm-focused .cm-selectionBackground, .cm-selectionBackground': {
            backgroundColor: '#b4d7ff !important',
          },
        }),
      ],
    });

    const view = new EditorView({
      state,
      parent: containerRef.current,
    });

    viewRef.current = view;
    useEditorStore.getState().setEditorView(view);

    return () => {
      view.destroy();
      viewRef.current = null;
      useEditorStore.getState().setEditorView(null);
    };
    // Only initialize once
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Sync external value changes with incremental diff
  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    const currentDoc = view.state.doc.toString();
    if (currentDoc !== value) {
      const changes = computeChanges(currentDoc, value);
      if (changes.length > 0) {
        view.dispatch({
          changes,
          // Don't add to user undo history for external updates
          annotations: [],
        });
      }
    }
  }, [value]);

  // Scroll editor to target line (inverse sync from PDF)
  const syncTargetLine = useEditorStore((s) => s.syncTargetLine);
  const syncSource = useEditorStore((s) => s.syncSource);
  useEffect(() => {
    const view = viewRef.current;
    if (!view || syncTargetLine === null || syncSource === 'editor') return;
    const lineCount = view.state.doc.lines;
    if (syncTargetLine < 1 || syncTargetLine > lineCount) return;
    const line = view.state.doc.line(syncTargetLine);
    _scrollState.programmatic = true;
    view.dispatch({
      effects: EditorView.scrollIntoView(line.from, { y: 'center' }),
    });
    useEditorStore.getState().setSyncTargetLine(null);
    // Clear flag after scroll settles
    setTimeout(() => { _scrollState.programmatic = false; }, 300);
  }, [syncTargetLine, syncSource]);

  return (
    <div style={{ height: '100%', width: '100%', overflow: 'hidden', position: 'relative' }}>
      <div
        ref={containerRef}
        style={{ height: '100%', width: '100%', overflow: 'hidden' }}
      />
      {showSelectionHint && (
        <Tooltip open title="选中文本后可使用 AI 修改选中部分" placement="top">
          <div style={{ position: 'fixed', top: selectionInfo?.position.top ?? 0, left: selectionInfo?.position.left ?? 0, width: 1, height: 1 }} />
        </Tooltip>
      )}
      <SelectionToolbar
        visible={toolbarVisible}
        position={selectionInfo?.position ?? { top: 0, left: 0 }}
        selectedText={selectionInfo?.text ?? ''}
        selectionFrom={selectionInfo?.from ?? 0}
        selectionTo={selectionInfo?.to ?? 0}
        fullLatex={value}
        onReplace={handleReplace}
        onClose={handleCloseToolbar}
      />
    </div>
  );
}
