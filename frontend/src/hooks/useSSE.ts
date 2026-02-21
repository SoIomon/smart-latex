import { useState, useCallback, useRef } from 'react';

interface UseSSEOptions {
  onMessage?: (data: string) => void;
  onError?: (error: Error) => void;
  onDone?: () => void;
}

export function useSSE(options?: UseSSEOptions) {
  const [connected, setConnected] = useState(false);
  const [data, setData] = useState('');
  const abortRef = useRef<AbortController | null>(null);

  const connect = useCallback(
    async (url: string, body?: Record<string, unknown>) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setConnected(true);
      setData('');

      try {
        const response = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: body ? JSON.stringify(body) : undefined,
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error(`SSE 连接失败: ${response.statusText}`);
        }

        const reader = response.body?.getReader();
        if (!reader) throw new Error('无法读取响应流');

        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              const eventData = line.slice(6);
              if (eventData === '[DONE]') {
                options?.onDone?.();
                setConnected(false);
                return;
              }
              setData((prev) => prev + eventData);
              options?.onMessage?.(eventData);
            }
          }
        }
      } catch (err) {
        if ((err as Error).name !== 'AbortError') {
          options?.onError?.(err as Error);
        }
      } finally {
        setConnected(false);
      }
    },
    [options]
  );

  const disconnect = useCallback(() => {
    abortRef.current?.abort();
    setConnected(false);
  }, []);

  return { connected, data, connect, disconnect };
}
