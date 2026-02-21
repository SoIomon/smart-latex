import { fetchSSE, parseSSEStream } from '../utils/sse';

export interface ChatSSEEvent {
  type: 'thinking' | 'tool_call' | 'tool_result' | 'content' | 'latex' | 'done' | 'error';
  data: string;
}

export async function* sendChatMessage(
  projectId: string,
  message: string,
  signal?: AbortSignal
): AsyncGenerator<ChatSSEEvent> {
  const response = await fetchSSE(
    `/api/v1/projects/${projectId}/chat`,
    { message },
    signal
  );

  for await (const raw of parseSSEStream(response)) {
    if (raw.data === '[DONE]') {
      yield { type: 'done', data: '' };
      return;
    }

    try {
      const parsed = JSON.parse(raw.data);

      // Map SSE event names to ChatSSEEvent types
      switch (raw.event) {
        case 'thinking':
          yield { type: 'thinking', data: parsed.message || '' };
          break;
        case 'tool_call':
          yield { type: 'tool_call', data: parsed.tool || '' };
          break;
        case 'tool_result':
          yield { type: 'tool_result', data: parsed.tool || '' };
          break;
        case 'chunk':
          yield { type: 'content', data: parsed.content || '' };
          break;
        case 'latex':
          yield { type: 'latex', data: parsed.content || '' };
          break;
        case 'done':
          yield { type: 'done', data: '' };
          break;
        case 'error':
          yield { type: 'error', data: parsed.error || 'Unknown error' };
          break;
        default:
          // Fallback: treat as content
          yield { type: 'content', data: parsed.content || parsed.data || raw.data };
          break;
      }
    } catch {
      if (raw.data.trim()) yield { type: 'content', data: raw.data };
    }
  }
}
