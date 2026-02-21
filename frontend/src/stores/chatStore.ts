import { create } from 'zustand';
import type { ChatMessage } from '../types';

interface ChatState {
  messages: ChatMessage[];
  sending: boolean;
  addMessage: (message: ChatMessage) => void;
  updateLastAssistantMessage: (content: string, latexUpdate?: string) => void;
  clearMessages: () => void;
  setSending: (sending: boolean) => void;
}

let msgCounter = 0;

export function createMessageId(): string {
  msgCounter += 1;
  return `msg-${Date.now()}-${msgCounter}`;
}

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  sending: false,

  addMessage: (message) => {
    set({ messages: [...get().messages, message] });
  },

  updateLastAssistantMessage: (content, latexUpdate) => {
    const msgs = [...get().messages];
    const lastIdx = msgs.length - 1;
    if (lastIdx >= 0 && msgs[lastIdx].role === 'assistant') {
      msgs[lastIdx] = {
        ...msgs[lastIdx],
        content,
        latex_update: latexUpdate ?? msgs[lastIdx].latex_update,
      };
      set({ messages: msgs });
    }
  },

  clearMessages: () => set({ messages: [] }),
  setSending: (sending) => set({ sending }),
}));
