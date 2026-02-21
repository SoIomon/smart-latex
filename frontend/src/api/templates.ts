import type { Template } from '../types';
import client from './client';
import { fetchSSE, parseSSEStream } from '../utils/sse';

export async function getTemplates(): Promise<Template[]> {
  const res = await client.get('/templates');
  return res.data;
}

export async function getTemplateDetail(id: string): Promise<Template> {
  const res = await client.get(`/templates/${id}`);
  return res.data;
}

export async function getTemplateContent(id: string): Promise<string> {
  const res = await client.get(`/templates/${id}/content`);
  return res.data.content;
}

export async function deleteTemplate(id: string): Promise<void> {
  await client.delete(`/templates/${id}`);
}

export interface TemplateGenerateEvent {
  type: 'chunk' | 'done' | 'error';
  content: string;
  template_id?: string;
  meta?: Record<string, unknown>;
}

export async function* generateTemplate(
  description: string,
  signal?: AbortSignal
): AsyncGenerator<TemplateGenerateEvent> {
  const response = await fetchSSE(
    '/api/v1/templates/generate',
    { description },
    signal
  );

  for await (const raw of parseSSEStream(response)) {
    if (raw.data === '[DONE]') return;
    try {
      const parsed = JSON.parse(raw.data);
      if (raw.event === 'error') {
        yield { type: 'error', content: parsed.error || '' };
      } else if (raw.event === 'done') {
        yield {
          type: 'done',
          content: '',
          template_id: parsed.template_id,
          meta: parsed.meta,
        };
      } else {
        yield { type: 'chunk', content: parsed.content || '' };
      }
    } catch {
      // not JSON, skip
    }
  }
}

export async function* generateTemplateFromFile(
  file: File,
  signal?: AbortSignal
): AsyncGenerator<TemplateGenerateEvent & { description?: string }> {
  const formData = new FormData();
  formData.append('file', file);

  const response = await fetch('/api/v1/templates/generate-from-file', {
    method: 'POST',
    body: formData,
    signal,
  });

  if (!response.ok || !response.body) {
    throw new Error(`Upload failed: ${response.status}`);
  }

  for await (const raw of parseSSEStream(response)) {
    if (raw.data === '[DONE]') return;
    try {
      const parsed = JSON.parse(raw.data);
      if (raw.event === 'error') {
        yield { type: 'error', content: parsed.error || '' };
      } else if (raw.event === 'status') {
        yield { type: 'chunk', content: `[${parsed.message}]\n` };
      } else if (raw.event === 'format') {
        yield { type: 'chunk', content: '', description: parsed.description };
      } else if (raw.event === 'done') {
        yield {
          type: 'done',
          content: '',
          template_id: parsed.template_id,
          meta: parsed.meta,
        };
      } else {
        yield { type: 'chunk', content: parsed.content || '' };
      }
    } catch {
      // not JSON, skip
    }
  }
}
