import type { Document } from '../types';
import client from './client';

export async function getDocuments(projectId: string): Promise<Document[]> {
  const res = await client.get(`/projects/${projectId}/documents`);
  return res.data;
}

export async function uploadDocument(
  projectId: string,
  file: File,
  onProgress?: (percent: number) => void
): Promise<Document> {
  const formData = new FormData();
  formData.append('file', file);
  const res = await client.post(`/projects/${projectId}/documents`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (e) => {
      if (e.total && onProgress) {
        onProgress(Math.round((e.loaded * 100) / e.total));
      }
    },
  });
  return res.data;
}

export async function deleteDocument(projectId: string, docId: string): Promise<void> {
  await client.delete(`/projects/${projectId}/documents/${docId}`);
}
