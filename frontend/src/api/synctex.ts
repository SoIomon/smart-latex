import client from './client';

export interface ForwardSyncResult {
  page: number;
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface InverseSyncResult {
  filename: string;
  line: number;
  column: number;
}

export interface LineMapResult {
  line_map: Record<string, { page: number; y: number }>;
  total_lines: number;
}

export async function forwardSync(
  projectId: string,
  line: number,
  column: number = 0,
): Promise<ForwardSyncResult> {
  const res = await client.get(`/projects/${projectId}/synctex/forward`, {
    params: { line, column },
  });
  return res.data;
}

export async function inverseSync(
  projectId: string,
  page: number,
  x: number,
  y: number,
): Promise<InverseSyncResult> {
  const res = await client.get(`/projects/${projectId}/synctex/inverse`, {
    params: { page, x, y },
  });
  return res.data;
}

export async function fetchLineMap(
  projectId: string,
): Promise<LineMapResult> {
  const res = await client.get(`/projects/${projectId}/synctex/linemap`);
  return res.data;
}
