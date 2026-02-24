import { useCallback } from 'react';
import { Segmented } from 'antd';
import { useParams } from 'react-router-dom';
import { useEditorStore } from '../../stores/editorStore';
import type { EditorMode } from '../../stores/editorStore';
import LatexEditor from './LatexEditor';
import PdfPreview from './PdfPreview';
import { forwardSync, inverseSync } from '../../api/synctex';

const modeOptions = [
  { label: '编辑器', value: 'edit' },
  { label: '预览', value: 'preview' },
  { label: '分屏', value: 'split' },
];

export default function EditorPanel() {
  const { projectId } = useParams<{ projectId: string }>();
  const { latexContent, setLatexContent, editorMode, setEditorMode, pdfUrl } =
    useEditorStore();

  const handleForwardSync = useCallback(
    async (line: number, column: number) => {
      if (!projectId) return;
      try {
        const result = await forwardSync(projectId, line, column);
        const store = useEditorStore.getState();
        store.setSyncSource('editor');
        store.setSyncTarget(result.page, result.y);
      } catch {
        // synctex not available, silently ignore
      }
    },
    [projectId],
  );

  const handlePageClick = useCallback(
    async (page: number, x: number, y: number) => {
      if (!projectId) return;
      try {
        const result = await inverseSync(projectId, page, x, y);
        const store = useEditorStore.getState();
        store.setSyncSource('pdf');
        store.setSyncTargetLine(result.line);
      } catch {
        // synctex not available, silently ignore
      }
    },
    [projectId],
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div
        style={{
          padding: '8px 16px',
          borderBottom: '1px solid #f0f0f0',
          background: '#fafafa',
        }}
      >
        <Segmented
          value={editorMode}
          options={modeOptions}
          onChange={(val) => setEditorMode(val as EditorMode)}
        />
      </div>
      <div style={{ flex: 1, overflow: 'hidden' }}>
        {editorMode === 'edit' && (
          <LatexEditor value={latexContent} onChange={setLatexContent} onForwardSync={handleForwardSync} />
        )}
        {editorMode === 'preview' && (
          <PdfPreview pdfUrl={pdfUrl} projectId={projectId} onPageClick={handlePageClick} />
        )}
        {editorMode === 'split' && (
          <div style={{ display: 'flex', height: '100%' }}>
            <div style={{ flex: 1, borderRight: '1px solid #f0f0f0', overflow: 'hidden' }}>
              <LatexEditor value={latexContent} onChange={setLatexContent} onForwardSync={handleForwardSync} />
            </div>
            <div style={{ flex: 1, overflow: 'hidden' }}>
              <PdfPreview pdfUrl={pdfUrl} projectId={projectId} onPageClick={handlePageClick} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
