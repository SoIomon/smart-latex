import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import 'react-pdf/dist/Page/AnnotationLayer.css';
import 'react-pdf/dist/Page/TextLayer.css';
import { Empty, Spin } from 'antd';
import { useEditorStore } from '../../stores/editorStore';
import { inverseSync } from '../../api/synctex';

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString();

interface PdfRegion {
  page: number;
  yStart: number; // PDF points from top
  yEnd: number;
}

interface LineMapEntry {
  line: number;
  page: number;
  y: number;
}

const PDF_PAGE_WIDTH = 595; // A4 width in PDF points
const PDF_PAGE_HEIGHT = 842; // A4 height in PDF points
const LINE_HEIGHT_PT = 14; // approximate line height padding in PDF points

function linesToPdfRegionsFromSorted(
  entries: LineMapEntry[],
  startLine: number,
  endLine: number,
): PdfRegion[] {
  if (entries.length === 0) return [];

  // Find nearest entry <= startLine
  let startIdx = 0;
  for (let i = 0; i < entries.length; i++) {
    if (entries[i].line <= startLine) startIdx = i;
    else break;
  }

  // Find nearest entry >= endLine
  let endIdx = entries.length - 1;
  for (let i = entries.length - 1; i >= 0; i--) {
    if (entries[i].line >= endLine) endIdx = i;
    else break;
  }

  // Ensure startIdx <= endIdx
  if (startIdx > endIdx) {
    const tmp = startIdx;
    startIdx = endIdx;
    endIdx = tmp;
  }

  // Collect entries in range and group by page
  const pageGroups = new Map<number, number[]>();
  for (let i = startIdx; i <= endIdx; i++) {
    const e = entries[i];
    if (!pageGroups.has(e.page)) pageGroups.set(e.page, []);
    pageGroups.get(e.page)!.push(e.y);
  }

  const regions: PdfRegion[] = [];
  for (const [page, ys] of pageGroups) {
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    regions.push({
      page,
      yStart: Math.max(0, minY - LINE_HEIGHT_PT),
      yEnd: maxY + LINE_HEIGHT_PT,
    });
  }

  return regions.sort((a, b) => a.page - b.page || a.yStart - b.yStart);
}

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
  const editorHighlightLines = useEditorStore((s) => s.editorHighlightLines);
  const lineMap = useEditorStore((s) => s.lineMap);

  // Pre-sort lineMap entries (only re-computed when lineMap changes, i.e. after compilation)
  const sortedEntries = useMemo(() => {
    if (!lineMap) return [];
    return Object.entries(lineMap)
      .map(([key, val]) => ({ line: parseInt(key, 10), page: val.page, y: val.y }))
      .filter((e) => !isNaN(e.line))
      .sort((a, b) => a.line - b.line);
  }, [lineMap]);

  // Compute PDF highlight regions from editor selection
  const highlightRegions = useMemo(() => {
    if (!editorHighlightLines || sortedEntries.length === 0) return [];
    return linesToPdfRegionsFromSorted(sortedEntries, editorHighlightLines.startLine, editorHighlightLines.endLine);
  }, [editorHighlightLines, sortedEntries]);

  // Listen for PDF text selection (selectionchange) -> inverse sync -> editor highlight
  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    let debounceTimer: ReturnType<typeof setTimeout> | null = null;

    const handleSelectionChange = () => {
      if (debounceTimer) clearTimeout(debounceTimer);
      debounceTimer = setTimeout(async () => {
        if (cancelled) return;

        const sel = document.getSelection();
        if (!sel || sel.isCollapsed || sel.rangeCount === 0) {
          // Only clear if previous highlight was from PDF selection
          // Check that the collapsed selection is relevant (within or was within PDF)
          const container = containerRef.current;
          if (container) {
            const anchor = sel?.anchorNode;
            if (anchor && container.contains(anchor)) {
              useEditorStore.getState().setPdfHighlightLines(null);
            }
          }
          return;
        }

        const range = sel.getRangeAt(0);
        const container = containerRef.current;
        if (!container || !container.contains(range.commonAncestorContainer)) {
          return; // selection is not in PDF container
        }

        // Skip if no editor is visible (preview-only mode)
        const editorMode = useEditorStore.getState().editorMode;
        if (editorMode === 'preview') return;

        // Find which page elements the start/end are in
        const startEl = range.startContainer instanceof Element
          ? range.startContainer
          : range.startContainer.parentElement;
        const endEl = range.endContainer instanceof Element
          ? range.endContainer
          : range.endContainer.parentElement;
        if (!startEl || !endEl) return;

        const startPageEl = startEl.closest('[data-page-number]');
        const endPageEl = endEl.closest('[data-page-number]');
        if (!startPageEl || !endPageEl) return;

        const startPage = parseInt(startPageEl.getAttribute('data-page-number')!, 10);
        const endPage = parseInt(endPageEl.getAttribute('data-page-number')!, 10);

        // Use individual Range objects for start/end to get accurate coordinates
        const startRange = document.createRange();
        startRange.setStart(range.startContainer, range.startOffset);
        startRange.setEnd(range.startContainer, range.startOffset);
        const startRangeRect = startRange.getBoundingClientRect();

        const endRange = document.createRange();
        endRange.setStart(range.endContainer, range.endOffset);
        endRange.setEnd(range.endContainer, range.endOffset);
        const endRangeRect = endRange.getBoundingClientRect();

        // Get page element coordinates
        const startPageRect = startPageEl.getBoundingClientRect();
        const endPageRect = endPageEl.getBoundingClientRect();

        // Convert to PDF points
        const startScaleX = PDF_PAGE_WIDTH / startPageRect.width;
        const startScaleY = PDF_PAGE_HEIGHT / startPageRect.height;
        const endScaleX = PDF_PAGE_WIDTH / endPageRect.width;
        const endScaleY = PDF_PAGE_HEIGHT / endPageRect.height;

        const startX = (startRangeRect.left - startPageRect.left) * startScaleX;
        const startY = (startRangeRect.top - startPageRect.top) * startScaleY;
        const endX = (endRangeRect.left - endPageRect.left) * endScaleX;
        const endY = (endRangeRect.top - endPageRect.top) * endScaleY;

        try {
          const [startResult, endResult] = await Promise.all([
            inverseSync(projectId, startPage, startX, startY),
            inverseSync(projectId, endPage, endX, endY),
          ]);
          if (cancelled) return;
          const minLine = Math.min(startResult.line, endResult.line);
          const maxLine = Math.max(startResult.line, endResult.line);
          useEditorStore.getState().setPdfHighlightLines({ startLine: minLine, endLine: maxLine });
        } catch {
          // inverseSync failed, silently ignore
        }
      }, 300);
    };

    document.addEventListener('selectionchange', handleSelectionChange);
    return () => {
      cancelled = true;
      document.removeEventListener('selectionchange', handleSelectionChange);
      if (debounceTimer) clearTimeout(debounceTimer);
    };
  }, [projectId]);

  // Clear pdfHighlightLines on unmount
  useEffect(() => {
    return () => {
      useEditorStore.getState().setPdfHighlightLines(null);
    };
  }, []);

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
        const scale = pageRect.height / PDF_PAGE_HEIGHT;
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
      const scaleX = PDF_PAGE_WIDTH / rect.width;
      const scaleY = PDF_PAGE_HEIGHT / rect.height;

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

  // Compute rendered page height from aspect ratio (no DOM measurement in render path)
  const renderedPageHeight = containerWidth * PDF_PAGE_HEIGHT / PDF_PAGE_WIDTH;
  const scale = renderedPageHeight / PDF_PAGE_HEIGHT;

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
          // Find highlight regions for this page
          const pageRegions = highlightRegions.filter((r) => r.page === pageNum);
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
                position: 'relative',
              }}
              onDoubleClick={(e) => handlePageClick(pageNum, e)}
            >
              <Page
                pageNumber={pageNum}
                width={containerWidth}
                renderTextLayer={true}
                renderAnnotationLayer={true}
              />
              {pageRegions.map((region, idx) => {
                const top = region.yStart * scale;
                const height = (region.yEnd - region.yStart) * scale;
                return (
                  <div
                    key={idx}
                    className="pdf-sync-highlight"
                    style={{
                      position: 'absolute',
                      top,
                      left: '50%',
                      transform: 'translateX(-50%)',
                      width: containerWidth,
                      height,
                    }}
                  />
                );
              })}
            </div>
          );
        })}
      </Document>
    </div>
  );
}
