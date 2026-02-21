import type { Project } from '../types';
import client from './client';

export async function getProjects(): Promise<Project[]> {
  const res = await client.get('/projects');
  return res.data.projects ?? res.data;
}

export async function getProject(id: string): Promise<Project> {
  const res = await client.get(`/projects/${id}`);
  return res.data;
}

export async function createProject(data: {
  name: string;
  description?: string;
  template_id?: string;
}): Promise<Project> {
  const res = await client.post('/projects', data);
  return res.data;
}

export async function updateProject(
  id: string,
  data: { name?: string; description?: string; latex_content?: string }
): Promise<Project> {
  const res = await client.put(`/projects/${id}`, data);
  return res.data;
}

export async function deleteProject(id: string): Promise<void> {
  await client.delete(`/projects/${id}`);
}
