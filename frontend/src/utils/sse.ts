export interface SSERawEvent {
  event: string;
  data: string;
}

/**
 * Parse an SSE ReadableStream into an async generator of raw events.
 * Supports AbortController via the signal that was passed to the original fetch.
 */
export async function* parseSSEStream(
  response: Response
): AsyncGenerator<SSERawEvent> {
  const reader = response.body?.getReader();
  if (!reader) throw new Error('Cannot read response stream');

  const decoder = new TextDecoder();
  let buffer = '';
  let currentEvent = 'message';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const rawLine of lines) {
        const line = rawLine.replace(/\r$/, '');
        if (line.startsWith('event: ')) {
          currentEvent = line.slice(7).trim();
        } else if (line.startsWith('data: ')) {
          const data = line.slice(6);
          yield { event: currentEvent, data };
          currentEvent = 'message';
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/**
 * Helper to create a fetch call with AbortController support for SSE endpoints.
 * Returns the Response and the AbortController so callers can cancel.
 */
export async function fetchSSE(
  url: string,
  body: Record<string, unknown>,
  signal?: AbortSignal
): Promise<Response> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
  }

  return response;
}
