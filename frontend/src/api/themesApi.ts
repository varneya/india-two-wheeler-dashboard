import type { HardwareReport, ThemesResult, ThemesStatus } from '../types/themes'
import { api, ApiError } from './client'

export async function fetchHardware(): Promise<HardwareReport> {
  try {
    const res = await api.get<HardwareReport>('/hardware')
    return res.data
  } catch (err) {
    // A 401 means the backend is up but admin-gated (shared host) — don't
    // let it read as "backend not running". ThemesTab keys off 'restricted'
    // in the message to tell the two apart.
    if (err instanceof ApiError && err.status === 401)
      throw new Error('Hardware info is restricted on this shared backend')
    throw err
  }
}

export async function fetchThemes(bikeId: string): Promise<ThemesResult> {
  const res = await api.get<ThemesResult>(`/bikes/${bikeId}/themes`)
  return res.data
}

export async function fetchThemesStatus(bikeId: string): Promise<ThemesStatus> {
  const res = await api.get<ThemesStatus>(`/bikes/${bikeId}/themes/status`)
  return res.data
}

export type PoolScope = 'bike' | 'brand'

export async function triggerThemesAnalysis(
  bikeId: string,
  method: string,
  config: Record<string, unknown>,
  pool_scope: PoolScope = 'bike',
): Promise<{ status: string }> {
  const res = await api.post<{ status: string }>(
    `/bikes/${bikeId}/themes/analyze`,
    { method, config, pool_scope },
  )
  return res.data
}

export async function pullOllamaModel(modelName: string): Promise<{ status: string }> {
  const res = await api.post<{ status: string }>(
    `/ollama/pull/${encodeURIComponent(modelName)}`,
  )
  return res.data
}

export interface PullProgress {
  status: string
  completed: number
  total: number
  percent: number
  error: string | null
  finished: boolean
}

export async function fetchPullProgress(modelName: string): Promise<PullProgress> {
  const res = await api.get<PullProgress>('/ollama/pull/status', {
    params: { model: modelName },
  })
  return res.data
}

export type KeywordMap = Record<string, string[]>

export async function fetchKeywordDefaults(): Promise<KeywordMap> {
  const res = await api.get<KeywordMap>('/themes/keyword-defaults')
  return res.data
}
