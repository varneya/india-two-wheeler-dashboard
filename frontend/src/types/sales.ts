export interface SalesDataPoint {
  month: string;
  units_sold: number;
  source_url?: string;
  confidence?: string;
  scraped_at: string;
  source?: string;          // 'autopunditz' | 'rushlane' | ...
}

// Display metadata per source — used by table pills, chart legends, etc.
// AutoPunditz is the primary brand-level source; RushLane is the secondary
// model-level source. Listed in priority order.
export const SOURCE_META: Record<string, { label: string; color: string }> = {
  autopunditz: { label: 'AutoPunditz', color: 'bg-violet-900/40 text-violet-300 border-violet-700/50' },
  rushlane:    { label: 'RushLane',    color: 'bg-blue-900/40 text-blue-300 border-blue-700/50' },
  bikedekho:   { label: 'BikeDekho',   color: 'bg-emerald-900/40 text-emerald-300 border-emerald-700/50' },
  youtube:     { label: 'YouTube',     color: 'bg-red-900/40 text-red-300 border-red-700/50' },
}

export interface MonthSummary {
  month: string;
  units_sold: number;
}

export interface Metrics {
  latest_month: MonthSummary | null;
  peak_month: MonthSummary | null;
  total_units: number;
  months_tracked: number;
  last_refresh: string | null;
}

export interface RefreshStatus {
  run_at: string | null;
  urls_tried: number;
  urls_success: number;
  error_msg: string | null;
}

// One per-source value reported for a given (bike, month).
export interface MonthSourceValue {
  source: string;           // 'autopunditz' | 'rushlane' | OCR-derived | ...
  units_sold: number;
  source_url: string | null;
}

// Returned by GET /api/bikes/{id}/sales/series — the canonical monthly time
// series with NaN gaps imputed and inline anomaly flags. One row per month
// from launch_month → most recent observed month.
//
// `units` is the median across reporting sources (or the imputed value).
// The full per-source breakdown is in `sources` so the UI can pop a
// distribution view on click; `n_sources` and `stddev` are precomputed
// summary fields for cheap rendering.
export interface SeriesHistoryPoint {
  month: string;            // 'YYYY-MM'
  units: number;            // observed (median) or imputed value
  imputed: boolean;
  impute_method: 'seasonal_naive' | 'linear' | 'ffill' | 'median' | null;
  anomaly: { is_anomaly: true; z_score: number } | null;
  n_sources: number;
  stddev: number | null;
  sources: MonthSourceValue[];
}

export interface SeriesAnomaly {
  month: string;
  units: number;
  prev_units: number;
  z_score: number;
  reason: string;
}

export interface SalesSeriesResponse {
  bike_id: string;
  history: SeriesHistoryPoint[];
  anomalies: SeriesAnomaly[];
}
