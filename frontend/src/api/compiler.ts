import type { CompileResult } from '../types';
import client from './client';
import { fetchSSE, parseSSEStream } from '../utils/sse';

export async function compileLatex(
  projectId: string,
  latexContent: string
): Promise<CompileResult> {
  const res = await client.post(`/projects/${projectId}/compile`, {
    latex_content: latexContent,
  });
  return res.data;
}

export interface CompileFixEvent {
  type: 'status' | 'fix' | 'done';
  data: {
    success?: boolean;
    pdf_url?: string;
    latex_content?: string;
    attempts?: number;
    errors?: string[];
    log?: string;
    message: string;
  };
}

export async function* compileAndFix(
  projectId: string,
  latexContent: string,
  signal?: AbortSignal
): AsyncGenerator<CompileFixEvent> {
  const response = await fetchSSE(
    `/api/v1/projects/${projectId}/compile-and-fix`,
    { latex_content: latexContent },
    signal
  );

  for await (const raw of parseSSEStream(response)) {
    try {
      const data = JSON.parse(raw.data);
      yield { type: raw.event as CompileFixEvent['type'], data };
    } catch {
      // skip
    }
  }
}

export function getPdfUrl(projectId: string): string {
  return `/api/v1/projects/${projectId}/pdf`;
}

export async function downloadPdf(projectId: string): Promise<void> {
  const res = await client.get(`/projects/${projectId}/pdf`, {
    responseType: 'blob',
  });
  const url = URL.createObjectURL(res.data as Blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'output.pdf';
  a.click();
  URL.revokeObjectURL(url);
}

export async function downloadWord(projectId: string): Promise<void> {
  const res = await client.get(`/projects/${projectId}/word`, {
    responseType: 'blob',
  });
  const url = URL.createObjectURL(res.data as Blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'output.docx';
  a.click();
  URL.revokeObjectURL(url);
}
