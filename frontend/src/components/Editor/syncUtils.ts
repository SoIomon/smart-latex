export interface LineMapEntry {
  line: number;
  page: number;
  y: number;
}

/**
 * Convert a lineMap Record to sorted entries array.
 */
export function toSortedEntries(
  lineMap: Record<string, { page: number; y: number }>,
): LineMapEntry[] {
  return Object.entries(lineMap)
    .map(([key, val]) => ({ line: parseInt(key, 10), page: val.page, y: val.y }))
    .filter((e) => !isNaN(e.line))
    .sort((a, b) => a.line - b.line);
}

/**
 * Interpolate a PDF position for a given source line number.
 * (Moved from PdfPreview.tsx)
 */
export function interpolatePosition(
  entries: LineMapEntry[],
  line: number,
): { page: number; y: number } {
  if (entries.length === 0) return { page: 1, y: 0 };

  let lowerIdx = 0;
  for (let i = 0; i < entries.length; i++) {
    if (entries[i].line <= line) lowerIdx = i;
    else break;
  }
  let upperIdx = entries.length - 1;
  for (let i = entries.length - 1; i >= 0; i--) {
    if (entries[i].line >= line) upperIdx = i;
    else break;
  }

  const lower = entries[lowerIdx];
  const upper = entries[upperIdx];

  if (lowerIdx === upperIdx || lower.page !== upper.page) {
    const useLower = line - lower.line <= upper.line - line;
    return useLower ? { page: lower.page, y: lower.y } : { page: upper.page, y: upper.y };
  }

  const t = (line - lower.line) / (upper.line - lower.line);
  return { page: lower.page, y: lower.y + t * (upper.y - lower.y) };
}

/**
 * Reverse interpolation: given a PDF {page, y}, find the closest editor line.
 */
export function reverseInterpolateLine(
  entries: LineMapEntry[],
  page: number,
  y: number,
): number | null {
  if (entries.length === 0) return null;

  // Filter to entries on this page
  const pageEntries = entries.filter((e) => e.page === page);
  if (pageEntries.length === 0) {
    // Find nearest page
    let closest = entries[0];
    for (const e of entries) {
      if (Math.abs(e.page - page) < Math.abs(closest.page - page)) {
        closest = e;
      }
    }
    return closest.line;
  }

  if (pageEntries.length === 1) return pageEntries[0].line;

  // Find bracketing entries by y coordinate
  let lowerIdx = 0;
  for (let i = 0; i < pageEntries.length; i++) {
    if (pageEntries[i].y <= y) lowerIdx = i;
    else break;
  }

  // If y is before the first entry on this page
  if (y < pageEntries[0].y) return pageEntries[0].line;
  // If y is after the last entry on this page
  if (y > pageEntries[pageEntries.length - 1].y) return pageEntries[pageEntries.length - 1].line;

  const lower = pageEntries[lowerIdx];
  const upperIdx = Math.min(lowerIdx + 1, pageEntries.length - 1);
  const upper = pageEntries[upperIdx];

  if (lowerIdx === upperIdx) return lower.line;

  // Interpolate line number
  const yRange = upper.y - lower.y;
  if (yRange === 0) return lower.line;

  const t = (y - lower.y) / yRange;
  return Math.round(lower.line + t * (upper.line - lower.line));
}
