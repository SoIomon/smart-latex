import { fetchSSE, parseSSEStream } from '../utils/sse';

export interface GenerateEvent {
  type: 'chunk' | 'done' | 'error' | 'stage' | 'outline';
  content: string;
  stage?: string;
  message?: string;
  progress?: number;
  detail?: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  outline?: any;
}

export async function* generateLatex(
  projectId: string,
  options?: { template_id?: string },
  signal?: AbortSignal
): AsyncGenerator<GenerateEvent> {
  const response = await fetchSSE(
    `/api/v1/projects/${projectId}/generate`,
    { template_id: options?.template_id || '' },
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
          content: parsed.content || '',
          message: parsed.message,
        };
      } else if (raw.event === 'stage') {
        yield {
          type: 'stage',
          content: '',
          stage: parsed.stage,
          message: parsed.message,
          progress: parsed.progress,
          detail: parsed.detail,
        };
      } else if (raw.event === 'outline') {
        yield {
          type: 'outline',
          content: '',
          message: parsed.message,
          outline: parsed.outline,
        };
      } else {
        yield { type: 'chunk', content: parsed.content || '' };
      }
    } catch {
      // not JSON, skip
    }
  }
}
