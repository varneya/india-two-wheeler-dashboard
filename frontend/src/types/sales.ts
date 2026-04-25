export interface SalesDataPoint {
  month: string;
  units_sold: number;
  source_url?: string;
  confidence?: string;
  scraped_at: string;
  source?: string;          // 'rushlane' | 'autopunditz' | 'fada' | ...
}

// Display metadata per source — used by table pills, chart legends, etc.
export const SOURCE_META: Record<string, { label: string; color: string }> = {
  rushlane:    { label: 'RushLane',    color: 'bg-blue-900/40 text-blue-300 border-blue-700/50' },
  autopunditz: { label: 'AutoPunditz', color: 'bg-violet-900/40 text-violet-300 border-violet-700/50' },
  fada:        { label: 'FADA Retail', color: 'bg-amber-900/40 text-amber-300 border-amber-700/50' },
  bikedekho:   { label: 'BikeDekho',   color: 'bg-emerald-900/40 text-emerald-300 border-emerald-700/50' },
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
