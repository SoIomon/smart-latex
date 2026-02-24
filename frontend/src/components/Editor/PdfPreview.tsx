import { useCallback, useEffect, useRef, useState } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import 'react-pdf/dist/Page/AnnotationLayer.css';
import 'react-pdf/dist/Page/TextLayer.css';
import { Empty, Spin } from 'antd';
import { useEditorStore } from '../../stores/editorStore';

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString();

interface PdfPreviewProps {
  pdfUrl: string | null;
  projectId?: string;
  onPageClick?: (page: number, x: number, y: number) => void;
}

export default function PdfPreview({ pdfUrl, projectId, onPageClick }: PdfPreviewProps) {
  const [numPages, setNumPages] = useState<number>(0);
  const [containerWidth, setContainerWidth] = useState<number>(600);
  const [loading, setLoading] = useState(true);
  const containerRef = useRef<HTMLDivElement>(null);
  const pageRefs = useRef<Map<number, HTMLDivElement>>(new Map());

  const syncTargetPage = useEditorStore((s) => s.syncTargetPage);
  const syncTargetY = useEditorStore((s) => s.syncTargetY);
  const syncSource = useEditorStore((s) => s.syncSource);

  // ResizeObserver for adaptive width
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setContainerWidth(entry.contentRect.width - 20); // padding
      }
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  // Forward sync: scroll PDF to target position
  useEffect(() => {
    if (syncTargetPage === null || syncSource === 'pdf') return;
    const pageEl = pageRefs.current.get(syncTargetPage);
    if (pageEl && containerRef.current) {
      const container = containerRef.current;
      const pageRect = pageEl.getBoundingClientRect();
      const containerRect = container.getBoundingClientRect();

      let yOffset = 0;
      if (syncTargetY !== null && pageRect.height > 0) {
        const pdfPageHeight = 842; // approximate A4
        const scale = pageRect.height / pdfPageHeight;
        yOffset = syncTargetY * scale;
      }

      const scrollToY = pageRect.top - containerRect.top + container.scrollTop + yOffset - container.clientHeight / 3;
      pdfProgrammaticScroll.current = true;
      container.scrollTo({ top: scrollToY, behavior: 'smooth' });
      setTimeout(() => { pdfProgrammaticScroll.current = false; }, 500);
    }
    // Clear target after handling to prevent re-triggering when syncSource changes
    useEditorStore.getState().setSyncTarget(null, null);
  }, [syncTargetPage, syncTargetY, syncSource]);

  const pdfProgrammaticScroll = useRef(false);

  const handlePageClick = useCallback(
    (pageNumber: number, event: React.MouseEvent<HTMLDivElement>) => {
      if (!onPageClick) return;
      const target = event.currentTarget;
      const rect = target.getBoundingClientRect();
      const clickX = event.clientX - rect.left;
      const clickY = event.clientY - rect.top;

      // Convert rendered coordinates to PDF points (72dpi)
      const pdfPageWidth = 595; // A4 width in points
      const pdfPageHeight = 842; // A4 height in points
      const scaleX = pdfPageWidth / rect.width;
      const scaleY = pdfPageHeight / rect.height;

      onPageClick(pageNumber, clickX * scaleX, clickY * scaleY);
    },
    [onPageClick],
  );

  if (!pdfUrl) {
    return (
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          height: '100%',
        }}
      >
        <Empty description="请先编译生成 PDF" />
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      style={{
        height: '100%',
        overflow: 'auto',
        background: '#525659',
        padding: '10px 0',
      }}
    >
      <Document
        file={pdfUrl}
        onLoadSuccess={({ numPages: n }) => {
          setNumPages(n);
          setLoading(false);
        }}
        onLoadError={() => setLoading(false)}
        loading={
          <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}>
            <Spin tip="加载 PDF..." />
          </div>
        }
      >
        {loading ? null : Array.from({ length: numPages }, (_, i) => {
          const pageNum = i + 1;
          return (
            <div
              key={pageNum}
              ref={(el) => {
                if (el) pageRefs.current.set(pageNum, el);
                else pageRefs.current.delete(pageNum);
              }}
              data-page-number={pageNum}
              style={{
                marginBottom: 10,
                display: 'flex',
                justifyContent: 'center',
                cursor: onPageClick ? 'crosshair' : 'default',
              }}
              onDoubleClick={(e) => handlePageClick(pageNum, e)}
            >
              <Page
                pageNumber={pageNum}
                width={containerWidth}
                renderTextLayer={true}
                renderAnnotationLayer={true}
              />
            </div>
          );
        })}
      </Document>
    </div>
  );
}
