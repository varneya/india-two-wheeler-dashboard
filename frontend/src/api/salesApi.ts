import axios from 'axios'
import type {
  Metrics,
  RefreshStatus,
  SalesDataPoint,
  SalesSeriesResponse,
} from '../types/sales'
import { API_BASE } from './client'

const api = axios.create({ baseURL: API_BASE })

export const fetchSales = (bikeId: string): Promise<SalesDataPoint[]> =>
  api.get<SalesDataPoint[]>(`/bikes/${bikeId}/sales`).then(r => r.data)

// Cheap, no-Prophet enriched history (imputed monthly series + inline anomaly
// flags). The unified Sales view always loads this on bike selection; the
// /forecast endpoint sits on top of it lazily.
export const fetchSalesSeries = (bikeId: string): Promise<SalesSeriesResponse> =>
  api.get<SalesSeriesResponse>(`/bikes/${bikeId}/sales/series`).then(r => r.data)

export const fetchMetrics = (bikeId: string): Promise<Metrics> =>
  api.get<Metrics>(`/bikes/${bikeId}/metrics`).then(r => r.data)

export const triggerRefresh = (bikeId: string): Promise<void> =>
  api.post(`/bikes/${bikeId}/refresh`).then(() => undefined)

export const fetchRefreshStatus = (): Promise<RefreshStatus> =>
  api.get<RefreshStatus>('/refresh/status').then(r => r.data)

// ---------------------------------------------------------------------------
// Forecast (Prophet) + missing-value imputation + anomaly detection
// ---------------------------------------------------------------------------

export interface ForecastHistoryPoint {
  month: string
  units: number
  imputed: boolean
  impute_method: 'seasonal_naive' | 'linear' | 'ffill' | 'median' | null
}

export interface ForecastPoint {
  month: string
  yhat: number
  yhat_lower: number
  yhat_upper: number
}

export interface AnomalyPoint {
  month: string
  units: number
  prev_units: number
  z_score: number
  reason: string
}

export interface ForecastResult {
  bike_id: string
  generated_at: string
  history: ForecastHistoryPoint[]
  forecast: ForecastPoint[]
  anomalies: AnomalyPoint[]
  horizon: number
  interval_width: number
  low_confidence: boolean
  n_observed: number
}

export interface ForecastPending {
  pending: true
  bike_id: string
  message: string
}

export interface ForecastStatus {
  bike_id: string
  stage: 'idle' | 'fitting' | 'done' | 'error'
  error: string | null
  started_at: number | null
  finished_at: number | null
}

export const fetchForecast = (
  bikeId: string,
  opts?: { horizon?: number; interval_width?: number; refresh?: boolean },
): Promise<ForecastResult | ForecastPending> => {
  const params = new URLSearchParams()
  if (opts?.horizon) params.set('horizon', String(opts.horizon))
  if (opts?.interval_width) params.set('interval_width', String(opts.interval_width))
  if (opts?.refresh) params.set('refresh', 'true')
  const qs = params.toString() ? `?${params.toString()}` : ''
  return api.get(`/bikes/${bikeId}/forecast${qs}`).then(r => r.data)
}

export const triggerForecastRefresh = (
  bikeId: string,
  opts?: { horizon?: number; interval_width?: number },
): Promise<{ status: string }> => {
  const params = new URLSearchParams()
  if (opts?.horizon) params.set('horizon', String(opts.horizon))
  if (opts?.interval_width) params.set('interval_width', String(opts.interval_width))
  const qs = params.toString() ? `?${params.toString()}` : ''
  return api.post(`/bikes/${bikeId}/forecast/refresh${qs}`).then(r => r.data)
}

export const fetchForecastStatus = (bikeId: string): Promise<ForecastStatus> =>
  api.get<ForecastStatus>(`/bikes/${bikeId}/forecast/status`).then(r => r.data)

// ---------------------------------------------------------------------------
// Brand-level "All models" view — same response shapes as bike-level so the
// chart + metric components reuse with no branching.
// ---------------------------------------------------------------------------

export interface BrandSecondaryPoint {
  month: string
  units: number
}

export interface BrandSeriesResponse {
  brand_id: string
  history: import('../types/sales').SeriesHistoryPoint[]
  anomalies: import('../types/sales').SeriesAnomaly[]
  // Optional secondary line — FADA retail values per month for the cross-source
  // comparison overlay on the brand-level chart.
  secondary_series: BrandSecondaryPoint[]
}

export const fetchBrandSalesSeries = (brandId: string): Promise<BrandSeriesResponse> =>
  api.get<BrandSeriesResponse>(`/brands/${brandId}/sales/series`).then(r => r.data)

export const fetchBrandMetrics = (brandId: string) =>
  api.get<import('../types/sales').Metrics>(`/brands/${brandId}/metrics`).then(r => r.data)

export const fetchBrandForecast = (
  brandId: string,
  opts?: { horizon?: number; interval_width?: number; refresh?: boolean },
): Promise<ForecastResult | ForecastPending> => {
  const params = new URLSearchParams()
  if (opts?.horizon) params.set('horizon', String(opts.horizon))
  if (opts?.interval_width) params.set('interval_width', String(opts.interval_width))
  if (opts?.refresh) params.set('refresh', 'true')
  const qs = params.toString() ? `?${params.toString()}` : ''
  return api.get(`/brands/${brandId}/forecast${qs}`).then(r => r.data)
}

export const triggerBrandForecastRefresh = (
  brandId: string,
  opts?: { horizon?: number; interval_width?: number },
): Promise<{ status: string }> => {
  const params = new URLSearchParams()
  if (opts?.horizon) params.set('horizon', String(opts.horizon))
  if (opts?.interval_width) params.set('interval_width', String(opts.interval_width))
  const qs = params.toString() ? `?${params.toString()}` : ''
  return api.post(`/brands/${brandId}/forecast/refresh${qs}`).then(r => r.data)
}

export const fetchBrandForecastStatus = (brandId: string): Promise<ForecastStatus> =>
  api.get<ForecastStatus>(`/brands/${brandId}/forecast/status`).then(r => r.data)
