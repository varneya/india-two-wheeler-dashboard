import type { HardwareReport, ThemesResult, ThemesStatus } from '../types/themes'
import { API_BASE as BASE } from './client'

export async function fetchHardware(): Promise<HardwareReport> {
  const res = await fetch(`${BASE}/hardware`)
  if (!res.ok) throw new Error('Failed to fetch hardware info')
  return res.json()
}

export async function fetchThemes(bikeId: string): Promise<ThemesResult> {
  const res = await fetch(`${BASE}/bikes/${bikeId}/themes`)
  if (!res.ok) throw new Error('Failed to fetch themes')
  return res.json()
}

export async function fetchThemesStatus(bikeId: string): Promise<ThemesStatus> {
  const res = await fetch(`${BASE}/bikes/${bikeId}/themes/status`)
  if (!res.ok) throw new Error('Failed to fetch themes status')
  return res.json()
}

export type PoolScope = 'bike' | 'brand'

export async function triggerThemesAnalysis(
  bikeId: string,
  method: string,
  config: Record<string, unknown>,
  pool_scope: PoolScope = 'bike',
): Promise<{ status: string }> {
  const res = await fetch(`${BASE}/bikes/${bikeId}/themes/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ method, config, pool_scope }),
  })
  if (!res.ok) throw new Error('Failed to trigger themes analysis')
  return res.json()
}

export async function pullOllamaModel(modelName: string): Promise<{ status: string }> {
  const res = await fetch(`${BASE}/ollama/pull/${encodeURIComponent(modelName)}`, {
    method: 'POST',
  })
  if (!res.ok) throw new Error('Failed to trigger model pull')
  return res.json()
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
  const res = await fetch(`${BASE}/ollama/pull/status?model=${encodeURIComponent(modelName)}`)
  if (!res.ok) throw new Error('Failed to fetch pull progress')
  return res.json()
}

export type KeywordMap = Record<string, string[]>

export async function fetchKeywordDefaults(): Promise<KeywordMap> {
  const res = await fetch(`${BASE}/themes/keyword-defaults`)
  if (!res.ok) throw new Error('Failed to fetch keyword defaults')
  return res.json()
}
