export interface Project {
  id: string;
  name: string;
  description: string;
  template_id?: string;
  template_name?: string;
  latex_content: string;
  created_at: string;
  updated_at: string;
}

export interface Document {
  id: string;
  project_id: string;
  filename: string;
  original_name: string;
  file_type: string;
  file_size: number;
  uploaded_at: string;
}

export interface Template {
  id: string;
  name: string;
  description: string;
  category?: string;
  preview_image?: string;
  variables: TemplateVariable[];
  is_builtin?: boolean;
}

export interface TemplateVariable {
  name: string;
  label: string;
  type: 'text' | 'textarea' | 'select';
  default_value?: string;
  options?: string[];
  required: boolean;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  latex_update?: string;
}

export interface CompileResult {
  success: boolean;
  pdf_url?: string;
  log: string;
  errors: string[];
}

export interface LLMConfig {
  api_key_masked: string;
  base_url: string;
  model: string;
  updated_at: string | null;
}
