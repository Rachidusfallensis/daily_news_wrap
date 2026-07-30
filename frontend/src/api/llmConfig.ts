import apiClient from '../apiClient'
import type { ProviderDescriptor, LLMDetectResult, LLMVerifyResult, LLMConfigOut, LLMConfigIn } from '../types'

export async function listProviders(): Promise<ProviderDescriptor[]> {
  return apiClient.get<ProviderDescriptor[]>('/api/llm-config/providers')
}

export async function getLLMConfigs(): Promise<LLMConfigOut[]> {
  return apiClient.get<LLMConfigOut[]>('/api/llm-config')
}

export async function saveLLMConfig(role: string, config: LLMConfigIn): Promise<{ status: string; role: string }> {
  return apiClient.put(`/api/llm-config/${role}`, config)
}

export async function deleteLLMConfig(role: string): Promise<{ status: string; role: string }> {
  return apiClient.del(`/api/llm-config/${role}`)
}

export async function detectProvider(apiKey: string): Promise<LLMDetectResult> {
  return apiClient.post<LLMDetectResult>('/api/llm-config/detect', { api_key: apiKey })
}

export interface VerifyRequest {
  provider: string
  api_key?: string
  base_url?: string
}

export async function verifyLLMConfig(params: VerifyRequest): Promise<LLMVerifyResult> {
  return apiClient.post<LLMVerifyResult>('/api/llm-config/verify', params)
}
