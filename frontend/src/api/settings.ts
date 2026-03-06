import client from './client';
import type { LLMConfig } from '../types';

export async function getLLMConfig(): Promise<LLMConfig> {
  const { data } = await client.get('/settings/llm');
  return data;
}

export async function updateLLMConfig(params: {
  api_key?: string;
  base_url?: string;
  model?: string;
}): Promise<LLMConfig> {
  const { data } = await client.put('/settings/llm', params);
  return data;
}

export async function testLLMConnection(params: {
  api_key?: string;
  base_url?: string;
  model?: string;
}): Promise<{ success: boolean; message: string }> {
  const { data } = await client.post('/settings/llm/test', params);
  return data;
}

export interface DiagnosticItem {
  name: string;
  status: 'ok' | 'warning' | 'error';
  message: string;
  suggestion: string;
}

export interface DiagnosticsResult {
  platform: string;
  items: DiagnosticItem[];
}

export async function runDiagnostics(): Promise<DiagnosticsResult> {
  const { data } = await client.get('/settings/diagnostics');
  return data;
}
