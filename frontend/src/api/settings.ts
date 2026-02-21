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
