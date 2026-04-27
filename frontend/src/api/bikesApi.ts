import axios from 'axios'
import type { Bike, CompareResponse, DiscoveryStatus } from '../types/bikes'
import { API_BASE } from './client'

const api = axios.create({ baseURL: API_BASE })

export interface Brand {
  id: string
  display: string
  model_count: number     // models in the curated catalogue
  db_bike_count: number   // models with sales data in DB
}

export interface BrandModel {
  id: string
  canonical: string
  display_name: string
  bikewale_slug: string | null
  in_db: boolean
  total_units: number
  months_tracked: number
  has_reviews: boolean
}

export const fetchBrands = (): Promise<Brand[]> =>
  api.get<Brand[]>('/brands').then(r => r.data)

export const fetchBrandModels = (brandId: string): Promise<BrandModel[]> =>
  api.get<BrandModel[]>(`/brands/${brandId}/models`).then(r => r.data)

export const fetchBikes = (): Promise<Bike[]> =>
  api.get<Bike[]>('/bikes').then(r => r.data)

export const fetchBike = (bikeId: string): Promise<Bike> =>
  api.get<Bike>(`/bikes/${bikeId}`).then(r => r.data)

export const triggerDiscovery = (): Promise<{ status: string }> =>
  api.post('/bikes/discover').then(r => r.data)

export const fetchDiscoveryStatus = (): Promise<DiscoveryStatus> =>
  api.get<DiscoveryStatus>('/bikes/discover/status').then(r => r.data)

export const triggerBikeRefresh = (bikeId: string): Promise<{ status: string }> =>
  api.post(`/bikes/${bikeId}/refresh`).then(r => r.data)

export const fetchCompare = (ids: string[]): Promise<CompareResponse> =>
  api
    .get<CompareResponse>('/compare', { params: { ids: ids.join(',') } })
    .then(r => r.data)

// ---------------------------------------------------------------------------
// Refresh-all orchestrator
// ---------------------------------------------------------------------------

// Per-stage cache counters reported by the backend.
// `cached`  = URLs whose body was unchanged since the previous refresh
//             (304 Not Modified or matching content hash) — work skipped.
// `fetched` = URLs that returned new bytes and were fully parsed.
interface StageCache {
  cached?: number
  fetched?: number
}

export interface RefreshAllStatus {
  running: boolean
  stage:
    | 'idle'
    | 'discovering'
    | 'reviews'
    | 'other_sources'
    | 'autopunditz'
    | 'retail'
    | 'done'
    | 'error'
  started_at: string | null
  finished_at: string | null
  duration_seconds: number | null
  force?: boolean
  discovery: StageCache & {
    stage: string
    urls_total: number
    urls_done: number
    bikes_found: number
  }
  reviews: StageCache & {
    bikes_total: number
    bikes_done: number
    current_bike: string | null
    current_bike_id: string | null
    reviews_added: number
  }
  other_sources: StageCache & {
    bikes_total: number
    bikes_done: number
    current_bike: string | null
    current_bike_id: string | null
    bikedekho_added: number
    zigwheels_added: number
    reddit_added: number
  }
  autopunditz?: StageCache & {
    posts_total: number
    posts_done: number
    model_rows_added: number
    brand_rows_added: number
  }
  retail: StageCache & {
    pdfs_total: number
    pdfs_done: number
    rows_added: number
  }
  error: string | null
}

export const triggerRefreshAll = (
  opts: { force?: boolean } = {},
): Promise<{ status: string }> =>
  api.post('/refresh-all', null, { params: opts.force ? { force: true } : {} })
    .then(r => r.data)

export const fetchRefreshAllStatus = (): Promise<RefreshAllStatus> =>
  api.get<RefreshAllStatus>('/refresh-all/status').then(r => r.data)

// ---------------------------------------------------------------------------
// Cross-source comparison (RushLane vs FADA)
// ---------------------------------------------------------------------------

export interface SourceComparisonPoint {
  month: string
  wholesale: number | null   // RushLane brand total for the month
  retail: number | null      // FADA retail for the brand
  source_gap: number | null  // signed wholesale - retail; UI shows abs value
}

export interface SourceComparisonResponse {
  brand_id: string
  brand_display: string
  series: SourceComparisonPoint[]
}

export const fetchSourceComparison = (
  brandId: string,
): Promise<SourceComparisonResponse> =>
  api
    .get<SourceComparisonResponse>(`/brands/${brandId}/wholesale-vs-retail`)
    .then(r => r.data)
