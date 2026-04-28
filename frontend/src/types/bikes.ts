export interface Bike {
  id: string
  brand: string
  model: string
  display_name: string
  keywords: string[]
  bikewale_slug: string | null
  bikewale_ok: number
  launch_month: string | null
  total_units: number
  months_tracked: number
  latest_month: string | null
  review_count: number
  themes_count: number
  has_reviews: boolean
  has_themes: boolean
}

export interface DiscoveryStatus {
  running: boolean
  stage: string
  urls_total: number
  urls_done: number
  bikes_found: number
  error: string | null
}

export interface ComparePoint {
  bike_id: string
  month: string
  units_sold: number
  // True when the value was filled by the imputation pipeline (no source
  // reported this month). Optional because old backends may not send it.
  imputed?: boolean
}

export interface CompareBike {
  id: string
  display_name: string
  brand: string
  total_units: number
  months_tracked: number
  peak_month: string | null
  peak_units: number
  avg_per_month: number
}

export interface CompareResponse {
  bikes: CompareBike[]
  series: ComparePoint[]
}
