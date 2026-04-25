export interface Theme {
  name: string
  sentiment: 'positive' | 'negative' | 'mixed'
  mention_count: number
  example_quotes: string[]
  keywords: string[]
}

export interface ThemesResult {
  method: string
  config: Record<string, unknown>
  themes: Theme[] | null
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
