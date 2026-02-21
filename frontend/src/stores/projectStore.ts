import { create } from 'zustand';
import type { Project } from '../types';
import * as projectApi from '../api/projects';

interface ProjectState {
  projects: Project[];
  currentProject: Project | null;
  loading: boolean;
  fetchProjects: () => Promise<void>;
  fetchProject: (id: string) => Promise<void>;
  createProject: (data: { name: string; description?: string; template_id?: string }) => Promise<Project>;
  updateProject: (id: string, data: { name?: string; description?: string; latex_content?: string }) => Promise<void>;
  deleteProject: (id: string) => Promise<void>;
  setCurrentProject: (project: Project | null) => void;
}

export const useProjectStore = create<ProjectState>((set, get) => ({
  projects: [],
  currentProject: null,
  loading: false,

  fetchProjects: async () => {
    set({ loading: true });
    try {
      const projects = await projectApi.getProjects();
      set({ projects });
    } finally {
      set({ loading: false });
    }
  },

  fetchProject: async (id: string) => {
    set({ loading: true });
    try {
      const project = await projectApi.getProject(id);
      set({ currentProject: project });
    } finally {
      set({ loading: false });
    }
  },

  createProject: async (data) => {
    const project = await projectApi.createProject(data);
    set({ projects: [...get().projects, project] });
    return project;
  },

  updateProject: async (id, data) => {
    const updated = await projectApi.updateProject(id, data);
    const current = get().currentProject;
    if (current?.id === id) {
      set({ currentProject: updated });
    }
    set({
      projects: get().projects.map((p) => (p.id === id ? updated : p)),
    });
  },

  deleteProject: async (id) => {
    await projectApi.deleteProject(id);
    set({
      projects: get().projects.filter((p) => p.id !== id),
      currentProject: get().currentProject?.id === id ? null : get().currentProject,
    });
  },

  setCurrentProject: (project) => set({ currentProject: project }),
}));
