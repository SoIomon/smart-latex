import { create } from 'zustand';
import type { Document } from '../types';
import * as docApi from '../api/documents';

interface DocumentState {
  documents: Document[];
  uploading: boolean;
  uploadProgress: number;
  fetchDocuments: (projectId: string) => Promise<void>;
  uploadDocument: (projectId: string, file: File) => Promise<void>;
  deleteDocument: (projectId: string, docId: string) => Promise<void>;
}

export const useDocumentStore = create<DocumentState>((set, get) => ({
  documents: [],
  uploading: false,
  uploadProgress: 0,

  fetchDocuments: async (projectId) => {
    const documents = await docApi.getDocuments(projectId);
    set({ documents });
  },

  uploadDocument: async (projectId, file) => {
    set({ uploading: true, uploadProgress: 0 });
    try {
      const doc = await docApi.uploadDocument(projectId, file, (percent) => {
        set({ uploadProgress: percent });
      });
      set({ documents: [...get().documents, doc] });
    } finally {
      set({ uploading: false, uploadProgress: 0 });
    }
  },

  deleteDocument: async (projectId, docId) => {
    await docApi.deleteDocument(projectId, docId);
    set({ documents: get().documents.filter((d) => d.id !== docId) });
  },
}));
