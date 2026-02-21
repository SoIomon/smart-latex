import { fetchSSE, parseSSEStream } from '../utils/sse';

export interface EditSelectionSSEEvent {
  type: 'chunk' | 'done' | 'error';
  data: string;
}

export interface EditSelectionParams {
  projectId: string;
  fullLatex: string;
  selectedText: string;
  instruction: string;
  selectionStart: number;
  selectionEnd: number;
}

export async function* editSelection(
  params: EditSelectionParams,
  signal?: AbortSignal
): AsyncGenerator<EditSelectionSSEEvent> {
  const response = await fetchSSE(
    `/api/v1/projects/${params.projectId}/edit-selection`,
    {
      full_latex: params.fullLatex,
      selected_text: params.selectedText,
      instruction: params.instruction,
      selection_start: params.selectionStart,
      selection_end: params.selectionEnd,
    },
    signal
  );

  for await (const raw of parseSSEStream(response)) {
    try {
      const parsed = JSON.parse(raw.data);
      if (raw.event === 'done') {
        yield { type: 'done', data: parsed.content || '' };
        return;
      }
      if (raw.event === 'error') {
        yield { type: 'error', data: parsed.error || '' };
        return;
      }
      yield { type: 'chunk', data: parsed.content || '' };
    } catch {
      if (raw.data.trim()) yield { type: 'chunk', data: raw.data };
    }
  }
}
