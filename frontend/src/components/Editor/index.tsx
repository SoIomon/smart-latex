import { Segmented } from 'antd';
import { useEditorStore } from '../../stores/editorStore';
import type { EditorMode } from '../../stores/editorStore';
import LatexEditor from './LatexEditor';
import PdfPreview from './PdfPreview';

const modeOptions = [
  { label: '编辑器', value: 'edit' },
  { label: '预览', value: 'preview' },
  { label: '分屏', value: 'split' },
];

export default function EditorPanel() {
  const { latexContent, setLatexContent, editorMode, setEditorMode, pdfUrl } =
    useEditorStore();

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
          <LatexEditor value={latexContent} onChange={setLatexContent} />
        )}
        {editorMode === 'preview' && <PdfPreview pdfUrl={pdfUrl} />}
        {editorMode === 'split' && (
          <div style={{ display: 'flex', height: '100%' }}>
            <div style={{ flex: 1, borderRight: '1px solid #f0f0f0', overflow: 'hidden' }}>
              <LatexEditor value={latexContent} onChange={setLatexContent} />
            </div>
            <div style={{ flex: 1, overflow: 'hidden' }}>
              <PdfPreview pdfUrl={pdfUrl} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
