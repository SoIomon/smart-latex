import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import 'react-pdf/dist/Page/AnnotationLayer.css';
import 'react-pdf/dist/Page/TextLayer.css';
import { Empty, Spin } from 'antd';
import { useEditorStore } from '../../stores/editorStore';
import { forwardSync, inverseSync } from '../../api/synctex';
import { interpolatePosition, reverseInterpolateLine, toSortedEntries } from './syncUtils';
import type { LineMapEntry } from './syncUtils';

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString();

interface PdfRegion {
  page: number;
  yStart: number; // PDF points from top
  yEnd: number;
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

  const startPos = interpolatePosition(entries, startLine);
  const endPos = interpolatePosition(entries, endLine);

  // Same page — single region
  if (startPos.page === endPos.page) {
    const yMin = Math.min(startPos.y, endPos.y);
    const yMax = Math.max(startPos.y, endPos.y);
    return [{
      page: startPos.page,
      yStart: Math.max(0, yMin - LINE_HEIGHT_PT),
      yEnd: yMax + LINE_HEIGHT_PT,
    }];
  }

  // Cross-page selection
  const regions: PdfRegion[] = [];

  // First page: from start position to page bottom
  regions.push({
    page: startPos.page,
    yStart: Math.max(0, startPos.y - LINE_HEIGHT_PT),
    yEnd: PDF_PAGE_HEIGHT,
  });

  // Intermediate full pages (include all, even figure/table-only pages)
  for (let p = startPos.page + 1; p < endPos.page; p++) {
    regions.push({ page: p, yStart: 0, yEnd: PDF_PAGE_HEIGHT });
  }

  // Last page: from top to end position
  regions.push({
    page: endPos.page,
    yStart: 0,
    yEnd: endPos.y + LINE_HEIGHT_PT,
  });

  return regions;
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
  const sortedEntries = useMemo<LineMapEntry[]>(() => {
    if (!lineMap) return [];
    return toSortedEntries(lineMap);
  }, [lineMap]);

  // Tier 1: lineMap interpolation — instant approximate highlight
  const approxRegions = useMemo(() => {
    if (!editorHighlightLines || sortedEntries.length === 0) return [];
    return linesToPdfRegionsFromSorted(sortedEntries, editorHighlightLines.startLine, editorHighlightLines.endLine);
  }, [editorHighlightLines, sortedEntries]);

  // Tier 2: forwardSync API — exact highlight (debounced, multi-point sampled, cached)
  const forwardSyncCache = useRef(new Map<number, { page: number; y: number }>());
  const [exactState, setExactState] = useState<{
    regions: PdfRegion[];
    startLine: number;
    endLine: number;
  } | null>(null);

  // Clear forwardSync cache when lineMap changes (new compilation)
  useEffect(() => {
    forwardSyncCache.current.clear();
  }, [lineMap]);

  useEffect(() => {
    if (!editorHighlightLines || !projectId) {
      setExactState(null);
      return;
    }

    let cancelled = false;
    const timer = setTimeout(async () => {
      if (cancelled) return;
      const { startLine, endLine } = editorHighlightLines;
      const cache = forwardSyncCache.current;

      // Build sample points: start, end, plus intermediate points for cross-page detection
      const linesToQuery = new Set<number>([startLine, endLine]);
      const range = endLine - startLine;
      if (range > 5) {
        const step = Math.max(1, Math.floor(range / 6));
        for (let l = startLine + step; l < endLine; l += step) {
          linesToQuery.add(l);
        }
      }

      // Query all sample points (cache-first, individual failures tolerated)
      const results = new Map<number, { page: number; y: number }>();
      for (const l of linesToQuery) {
        const cached = cache.get(l);
        if (cached) results.set(l, cached);
      }

      const uncached = [...linesToQuery].filter((l) => !results.has(l));
      if (uncached.length > 0) {
        await Promise.all(
          uncached.map((l) =>
            forwardSync(projectId, l)
              .then((r) => {
                const pos = { page: r.page, y: r.y };
                cache.set(l, pos);
                results.set(l, pos);
              })
              .catch(() => {}), // individual failure is OK
          ),
        );
      }
      if (cancelled || results.size === 0) return;

      // Group results by page → {minY, maxY}
      const pageYs = new Map<number, { min: number; max: number }>();
      for (const pos of results.values()) {
        const entry = pageYs.get(pos.page);
        if (entry) {
          entry.min = Math.min(entry.min, pos.y);
          entry.max = Math.max(entry.max, pos.y);
        } else {
          pageYs.set(pos.page, { min: pos.y, max: pos.y });
        }
      }

      // Build regions from page groups
      const pages = [...pageYs.keys()].sort((a, b) => a - b);
      const regions: PdfRegion[] = [];
      for (let i = 0; i < pages.length; i++) {
        const p = pages[i];
        const ys = pageYs.get(p)!;
        const isFirst = i === 0;
        const isLast = i === pages.length - 1;
        regions.push({
          page: p,
          yStart: isFirst ? Math.max(0, ys.min - LINE_HEIGHT_PT) : 0,
          yEnd: isLast ? ys.max + LINE_HEIGHT_PT : PDF_PAGE_HEIGHT,
        });
      }

      // Fill intermediate pages that had no sample points (e.g., figure-only pages)
      if (pages.length >= 2) {
        for (let p = pages[0] + 1; p < pages[pages.length - 1]; p++) {
          if (!pageYs.has(p)) {
            regions.push({ page: p, yStart: 0, yEnd: PDF_PAGE_HEIGHT });
          }
        }
        regions.sort((a, b) => a.page - b.page);
      }

      setExactState({ regions, startLine, endLine });
    }, 150);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [editorHighlightLines, projectId]);

  // Final highlight: prefer exact regions only if they match current selection
  const exactRegions =
    exactState &&
    editorHighlightLines &&
    exactState.startLine === editorHighlightLines.startLine &&
    exactState.endLine === editorHighlightLines.endLine
      ? exactState.regions
      : null;
  const highlightRegions = exactRegions ?? approxRegions;

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
  const syncTargetSmooth = useEditorStore((s) => s.syncTargetSmooth);
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
      const behavior = syncTargetSmooth ? 'smooth' : 'auto';
      const flagDuration = syncTargetSmooth ? 500 : 100;
      pdfProgrammaticScroll.current = true;
      container.scrollTo({ top: scrollToY, behavior });
      setTimeout(() => { pdfProgrammaticScroll.current = false; }, flagDuration);
    }
    // Clear target after handling to prevent re-triggering when syncSource changes
    useEditorStore.getState().setSyncTarget(null, null);
  }, [syncTargetPage, syncTargetY, syncSource, syncTargetSmooth]);

  const pdfProgrammaticScroll = useRef(false);

  // PDF scroll auto-follow: reverse lookup editor line from scroll position (RAF-throttled)
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    let rafId: number | null = null;
    let lastFollowLine = -1;

    const handleScroll = () => {
      if (pdfProgrammaticScroll.current) return;
      if (rafId !== null) return; // throttle to 1 per frame
      rafId = requestAnimationFrame(() => {
        rafId = null;
        const state = useEditorStore.getState();
        if (!state.autoFollow || sortedEntries.length === 0 || state.activePane !== 'pdf') return;

        // Find which page is at the viewport center
        const containerRect = container.getBoundingClientRect();
        const centerY = containerRect.top + containerRect.height / 2;

        let targetPage = 1;
        let targetYInPage = 0;

        for (const [pageNum, pageEl] of pageRefs.current.entries()) {
          const pageRect = pageEl.getBoundingClientRect();
          if (pageRect.top <= centerY && pageRect.bottom >= centerY) {
            targetPage = pageNum;
            const relativeY = centerY - pageRect.top;
            const scaleY = PDF_PAGE_HEIGHT / pageRect.height;
            targetYInPage = relativeY * scaleY;
            break;
          }
        }

        const line = reverseInterpolateLine(sortedEntries, targetPage, targetYInPage);
        if (line !== null && line !== lastFollowLine) {
          lastFollowLine = line;
          state.setSyncSource('pdf');
          state.setSyncTargetLine(line);
        }
      });
    };

    container.addEventListener('scroll', handleScroll, { passive: true });
    return () => {
      container.removeEventListener('scroll', handleScroll);
      if (rafId !== null) cancelAnimationFrame(rafId);
    };
  }, [sortedEntries]);

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
      onMouseEnter={() => useEditorStore.getState().setActivePane('pdf')}
      onMouseLeave={() => {
        const s = useEditorStore.getState();
        if (s.activePane === 'pdf') s.setActivePane(null);
      }}
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
              onClick={(e) => handlePageClick(pageNum, e)}
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
