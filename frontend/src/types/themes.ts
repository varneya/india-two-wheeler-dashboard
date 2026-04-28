export interface Theme {
  name: string
  sentiment: 'positive' | 'negative' | 'mixed'
  mention_count: number
  example_quotes: string[]
  keywords: string[]
  // Populated only when the analysis was run with pool_scope='brand':
  // fraction of this theme's reviews attributable to the originally-selected
  // bike (0 = entirely from siblings, 1 = uniquely about this bike).
  localized_share?: number | null
  bike_review_counts?: Record<string, number>
  // Per-theme average rating, computed from any attributed reviews carrying
  // overall_rating. Null if no rated reviews were attributed.
  avg_rating?: number | null
  rating_count?: number
}

export interface ThemesMetrics {
  npmi: number | null
  theme_diversity: number | null
  n_reviews: number
}

export interface ThemesResult {
  method: string
  config: Record<string, unknown>
  themes: Theme[] | null
  metrics?: ThemesMetrics | null
  run_at?: string
  error?: string | null
}

export interface ThemesStatus {
  running: boolean
  total_analyses: number
  last_method: string | null
  last_run_at: string | null
}

export interface OllamaModel {
  name: string
  size_gb: number
  size_label: string
  quality: string
  description: string
  pulled: boolean
  // Marks the canonical default at this RAM tier so the UI can star/highlight
  // it. Optional because older backends may not send it.
  recommended?: boolean
}

export interface HardwareInfo {
  chip: string
  generation: string
  ram_gb: number
}

export interface HardwareReport {
  hardware: HardwareInfo
  ollama: {
    installed: boolean
    running: boolean
    pulled_models: string[]
  }
  recommended_models: OllamaModel[]
}
