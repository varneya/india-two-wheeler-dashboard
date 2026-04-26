import { useQuery } from '@tanstack/react-query'
import { Cpu, Loader2, Sparkles } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { fetchBikes } from '../api/bikesApi'
import {
  fetchHardware,
  fetchPullProgress,
  fetchThemes,
  fetchThemesStatus,
  pullOllamaModel,
  triggerThemesAnalysis,
  type KeywordMap,
  type PoolScope,
  type PullProgress,
} from '../api/themesApi'
import { useSelectedBike } from '../context/SelectedBike'
import type { HardwareReport, OllamaModel, Theme, ThemesResult } from '../types/themes'
import { KeywordEditor } from './KeywordEditor'
import { Badge } from './ui/badge'
import { Button } from './ui/button'
import { Card, CardContent } from './ui/card'

// ---------------------------------------------------------------------------
// Tiny helpers
// ---------------------------------------------------------------------------
function SentimentBadge({ s }: { s: string }) {
  const variant: 'success' | 'destructive' | 'warning' =
    s === 'positive' ? 'success' : s === 'negative' ? 'destructive' : 'warning'
  return (
    <Badge variant={variant} className="rounded-full">
      {s}
    </Badge>
  )
}

// ---------------------------------------------------------------------------
// Hardware card
// ---------------------------------------------------------------------------
function formatBytes(n: number): string {
  if (!n) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  let v = n
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v.toFixed(v >= 100 ? 0 : 1)} ${units[i]}`
}

function HardwareCard({
  hw,
  onPull,
}: {
  hw: HardwareReport
  onPull: (model: string) => void
}) {
  const { hardware, ollama, recommended_models } = hw
  const [progress, setProgress] = useState<Record<string, PullProgress>>({})
  const pollersRef = useRef<Record<string, ReturnType<typeof setInterval>>>({})

  // If Ollama is running and at least one model is pulled, collapse by default —
  // the user has already done the one-time setup and doesn't need to see this
  // every time. They can click the row to expand if they want to pull another.
  const hasReadyModel = ollama.running && (ollama.pulled_models?.length ?? 0) > 0
  const [expanded, setExpanded] = useState(!hasReadyModel)

  function stopPolling(name: string) {
    const t = pollersRef.current[name]
    if (t) {
      clearInterval(t)
      delete pollersRef.current[name]
    }
  }

  // Cleanup intervals on unmount
  useEffect(() => () => {
    Object.values(pollersRef.current).forEach(clearInterval)
    pollersRef.current = {}
  }, [])

  async function handlePull(name: string) {
    if (pollersRef.current[name]) return // already polling
    setProgress(p => ({
      ...p,
      [name]: { status: 'starting', completed: 0, total: 0, percent: 0, error: null, finished: false },
    }))
    try {
      await pullOllamaModel(name)
    } catch (e) {
      setProgress(p => ({
        ...p,
        [name]: { ...p[name], status: 'error', error: String(e), finished: true },
      }))
      return
    }

    pollersRef.current[name] = setInterval(async () => {
      try {
        const pr = await fetchPullProgress(name)
        setProgress(p => ({ ...p, [name]: pr }))
        if (pr.finished) {
          stopPolling(name)
          // Refresh hardware so the model shows as ready
          setTimeout(() => onPull(name), 500)
        }
      } catch {
        stopPolling(name)
      }
    }, 600)
  }

  // ---- Collapsed state: tiny one-liner ----
  if (!expanded) {
    const readyModel = ollama.pulled_models?.[0] ?? '—'
    return (
      <button
        onClick={() => setExpanded(true)}
        className="w-full flex items-center justify-between bg-card hover:bg-accent/50 border border-border rounded-xl px-4 py-2.5 transition-colors"
      >
        <div className="flex items-center gap-3">
          <div className="w-2 h-2 rounded-full bg-emerald-400" />
          <span className="text-sm text-muted-foreground">
            Local LLM ready · <span className="font-mono text-foreground">{readyModel}</span>
          </span>
          <span className="text-xs text-muted-foreground/70 hidden sm:inline">
            on {hardware.chip} · {hardware.ram_gb} GB
          </span>
        </div>
        <span className="text-xs text-muted-foreground hover:text-foreground">Change ▾</span>
      </button>
    )
  }

  // ---- Expanded state: full card ----
  return (
    <Card>
      <CardContent className="space-y-4">
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-primary/15 border border-primary/30 flex items-center justify-center text-primary">
          <Cpu className="w-4 h-4" />
        </div>
        <div>
          <p className="font-semibold text-foreground text-sm">{hardware.chip}</p>
          <p className="text-muted-foreground text-xs">{hardware.ram_gb} GB unified memory</p>
        </div>
        <div className="ml-auto flex items-center gap-1.5">
          <div
            className={`w-2 h-2 rounded-full ${
              ollama.running ? 'bg-emerald-400' : ollama.installed ? 'bg-amber-400' : 'bg-red-400'
            }`}
          />
          <span className="text-xs text-muted-foreground">
            {ollama.running ? 'Ollama running' : ollama.installed ? 'Ollama installed (not running)' : 'Ollama not installed'}
          </span>
          {hasReadyModel && (
            <button
              onClick={() => setExpanded(false)}
              className="ml-2 text-xs text-muted-foreground hover:text-foreground"
              title="Collapse"
            >
              ▴
            </button>
          )}
        </div>
      </div>

      {!ollama.installed && (
        <div className="bg-slate-700/50 border border-slate-600 rounded-lg px-4 py-3 text-sm text-slate-300 space-y-1">
          <p className="font-medium text-white">Install Ollama to use local models:</p>
          <code className="block text-xs bg-slate-900 rounded px-2 py-1 text-emerald-300 mt-1">
            chmod +x scripts/install_ollama.sh && ./scripts/install_ollama.sh
          </code>
        </div>
      )}

      {!ollama.running && ollama.installed && (
        <div className="bg-amber-900/20 border border-amber-700/40 rounded-lg px-4 py-3 text-sm text-amber-300">
          Ollama is installed but not running.{' '}
          <code className="bg-amber-900/40 px-1 rounded text-xs">ollama serve</code>
        </div>
      )}

      {ollama.running && recommended_models.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-medium text-slate-400 uppercase tracking-wide">
            Recommended models for your Mac
          </p>
          <div className="space-y-1.5">
            {recommended_models.map((m: OllamaModel) => {
              const pr = progress[m.name]
              const isPulling = pr && !pr.finished
              const justFinished = pr && pr.finished && !pr.error
              const failed = pr && pr.error

              return (
                <div
                  key={m.name}
                  className="bg-slate-700/40 rounded-lg px-3 py-2 space-y-1.5"
                >
                  <div className="flex items-center gap-3">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-white font-mono">{m.name}</p>
                      <p className="text-xs text-slate-400 truncate">
                        {m.size_label} · {m.quality} · {m.description}
                      </p>
                    </div>
                    {m.pulled || justFinished ? (
                      <span className="text-xs text-emerald-400 font-medium shrink-0">✓ ready</span>
                    ) : isPulling ? (
                      <span className="text-xs text-amber-400 font-mono shrink-0 tabular-nums">
                        {pr.percent.toFixed(1)}%
                      </span>
                    ) : (
                      <Button
                        size="sm"
                        onClick={() => handlePull(m.name)}
                        className="shrink-0"
                      >
                        Pull
                      </Button>
                    )}
                  </div>

                  {/* Progress bar */}
                  {isPulling && (
                    <div className="space-y-1">
                      <div className="h-1.5 w-full bg-slate-900/60 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-gradient-to-r from-blue-500 to-cyan-400 transition-all duration-300 ease-out"
                          style={{ width: `${Math.max(pr.percent, 2)}%` }}
                        />
                      </div>
                      <div className="flex items-center justify-between text-[10px] text-slate-400 font-mono tabular-nums">
                        <span className="capitalize">{pr.status}</span>
                        <span>
                          {pr.total > 0
                            ? `${formatBytes(pr.completed)} / ${formatBytes(pr.total)}`
                            : '...'}
                        </span>
                      </div>
                    </div>
                  )}
                  {failed && (
                    <p className="text-[10px] text-destructive">Error: {pr.error}</p>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Method picker cards
// ---------------------------------------------------------------------------
type Method = 'keyword' | 'tfidf' | 'semantic' | 'bertopic' | 'llm'

const METHODS: {
  id: Method
  label: string
  icon: string
  description: string
  badge?: string
}[] = [
  {
    id: 'keyword',
    label: 'Keyword Rules',
    icon: '🔑',
    description: 'Fast, deterministic. Matches reviews against predefined motorcycle keyword buckets. No ML, no API. Best for a quick first pass.',
    badge: 'Instant',
  },
  {
    id: 'tfidf',
    label: 'TF-IDF Clustering',
    icon: '📊',
    description: 'Classical ML baseline. TF-IDF vectors + K-Means. Bag-of-words, no semantic understanding.',
    badge: 'classical',
  },
  {
    id: 'semantic',
    label: 'Semantic Clustering',
    icon: '🧬',
    description: 'Embeds each review via local Ollama (nomic-embed-text). Clusters with HDBSCAN, names with c-TF-IDF. Captures semantic similarity that TF-IDF misses.',
    badge: 'Solid',
  },
  {
    id: 'bertopic',
    label: 'BERTopic Pipeline',
    icon: '🚀',
    description: 'Full BERTopic recipe — embeddings + UMAP + HDBSCAN + c-TF-IDF, with optional LLM-based theme name refinement using local Mistral. Best quality.',
    badge: 'Power user',
  },
  {
    id: 'llm',
    label: 'LLM Analysis',
    icon: '🤖',
    description: 'Sends reviews to a language model (Claude or a local Ollama model) for deep qualitative understanding, nuanced sentiment, and richer theme labels.',
    badge: 'AI',
  },
]

function MethodCard({
  method,
  selected,
  onClick,
}: {
  method: (typeof METHODS)[number]
  selected: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={`relative text-left p-4 rounded-xl border transition-all ${
        selected
          ? 'bg-primary/15 border-primary/70 ring-1 ring-primary/50'
          : 'bg-card border-border hover:border-input'
      }`}
    >
      {method.badge && (
        <Badge variant="secondary" className="absolute top-3 right-3 rounded-full">
          {method.badge}
        </Badge>
      )}
      <div className="text-2xl mb-2">{method.icon}</div>
      <p className="font-semibold text-foreground text-sm mb-1">{method.label}</p>
      <p className="text-xs text-muted-foreground leading-relaxed">{method.description}</p>
    </button>
  )
}

// ---------------------------------------------------------------------------
// Config panel (per method)
// ---------------------------------------------------------------------------
function ConfigPanel({
  method,
  hw,
  nClusters,
  setNClusters,
  llmBackend,
  setLlmBackend,
  llmNaming,
  setLlmNaming,
  onKeywordsChange,
}: {
  method: Method
  hw: HardwareReport | null
  nClusters: number
  setNClusters: (n: number) => void
  llmBackend: string
  setLlmBackend: (s: string) => void
  llmNaming: boolean
  setLlmNaming: (b: boolean) => void
  onKeywordsChange: (m: KeywordMap) => void
}) {
  if (method === 'keyword') {
    return <KeywordEditor onChange={onKeywordsChange} />
  }

  if (method === 'tfidf') {
    return (
      <Card>
        <CardContent className="space-y-3">
          <p className="text-sm font-medium text-foreground">TF-IDF Configuration</p>
          <div className="flex items-center gap-4">
            <label className="text-sm text-muted-foreground w-36 shrink-0">Number of clusters</label>
            <input
              type="range"
              min={3}
              max={12}
              value={nClusters}
              onChange={e => setNClusters(Number(e.target.value))}
              className="flex-1 accent-primary"
            />
            <span className="text-sm font-mono text-foreground w-6 text-center">{nClusters}</span>
          </div>
          <p className="text-xs text-muted-foreground/70">
            More clusters = finer-grained themes; fewer = broader buckets. 6 is a good default.
          </p>
        </CardContent>
      </Card>
    )
  }

  if (method === 'semantic') {
    return (
      <Card>
        <CardContent className="space-y-2">
          <p className="text-sm font-medium text-foreground">Semantic Clustering</p>
          <p className="text-xs text-muted-foreground leading-relaxed">
            Embeds reviews via local Ollama (<code className="text-foreground">nomic-embed-text</code>),
            clusters with HDBSCAN, names buckets via c-TF-IDF. No K to pick — the
            algorithm finds the right number. Falls back to KMeans + silhouette for
            small or low-density datasets. Typically 5–10 seconds.
          </p>
          {!hw?.ollama?.running && (
            <p className="text-xs text-amber-400 mt-2">
              ⚠ Ollama isn't running. Start it with{' '}
              <code className="bg-card px-1 rounded">ollama serve</code> and pull{' '}
              <code className="bg-card px-1 rounded">nomic-embed-text</code>.
            </p>
          )}
        </CardContent>
      </Card>
    )
  }

  if (method === 'bertopic') {
    return (
      <Card>
        <CardContent className="space-y-3">
          <p className="text-sm font-medium text-foreground">BERTopic Pipeline</p>
          <p className="text-xs text-muted-foreground leading-relaxed">
            Full pipeline: embeddings → UMAP dim-reduction → HDBSCAN → c-TF-IDF.
            Adds a Mistral 7B pass to refine cluster names from generic terms
            (e.g. <span className="italic">"comfort / cushion"</span>) into polished
            labels (e.g. <span className="italic">"Riding Comfort"</span>). 20–40s.
          </p>
          <label className="flex items-center gap-3 px-3 py-2 rounded-lg border border-border bg-secondary/30 cursor-pointer">
            <input
              type="checkbox"
              checked={llmNaming}
              onChange={e => setLlmNaming(e.target.checked)}
              className="accent-primary"
            />
            <div>
              <p className="text-sm text-foreground">LLM-refined theme names</p>
              <p className="text-xs text-muted-foreground">
                Uses local Mistral 7B to coin 2–3 word names from cluster quotes.
              </p>
            </div>
          </label>
          {!hw?.ollama?.running && (
            <p className="text-xs text-amber-400">
              ⚠ Ollama isn't running. Start it and pull{' '}
              <code className="bg-card px-1 rounded">nomic-embed-text</code>{' '}
              {llmNaming && (
                <>
                  + <code className="bg-card px-1 rounded">mistral:7b</code>
                </>
              )}.
            </p>
          )}
        </CardContent>
      </Card>
    )
  }

  // LLM
  const pulledModels = hw?.ollama?.pulled_models ?? []
  const ollamaModels = pulledModels.map(m => ({ value: `ollama:${m}`, label: m }))
  const allOptions = [
    { value: 'claude', label: 'Claude (Anthropic API)' },
    ...ollamaModels,
  ]

  return (
    <Card>
      <CardContent className="space-y-3">
      <p className="text-sm font-medium text-foreground">LLM Backend</p>
      <div className="grid gap-2">
        {allOptions.map(opt => (
          <label
            key={opt.value}
            className={`flex items-center gap-3 px-3 py-2.5 rounded-lg border cursor-pointer transition-colors ${
              llmBackend === opt.value
                ? 'border-primary/60 bg-primary/15'
                : 'border-border bg-secondary/30 hover:border-input'
            }`}
          >
            <input
              type="radio"
              name="llm_backend"
              value={opt.value}
              checked={llmBackend === opt.value}
              onChange={() => setLlmBackend(opt.value)}
              className="accent-primary"
            />
            <div>
              <p className="text-sm text-foreground">{opt.label}</p>
              {opt.value === 'claude' && (
                <p className="text-xs text-muted-foreground">Requires ANTHROPIC_API_KEY in backend/.env</p>
              )}
            </div>
          </label>
        ))}
        {ollamaModels.length === 0 && (
          <p className="text-xs text-muted-foreground/70 px-1">
            No Ollama models pulled yet. Use the hardware panel above to pull one.
          </p>
        )}
      </div>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Theme result card
// ---------------------------------------------------------------------------
function ThemeCard({ theme, rank }: { theme: Theme; rank: number }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <Card className="py-4 gap-3">
      <CardContent className="space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2.5 min-w-0">
          <span className="text-xs font-bold text-muted-foreground/70 w-5 shrink-0">#{rank}</span>
          <p className="font-semibold text-foreground text-sm leading-tight">{theme.name}</p>
        </div>
        <div className="flex items-center gap-2 shrink-0 flex-wrap justify-end">
          {typeof theme.avg_rating === 'number' && (theme.rating_count ?? 0) > 0 && (
            <Badge
              variant={theme.avg_rating >= 4 ? 'success' : theme.avg_rating >= 3 ? 'info' : 'warning'}
              className="rounded-full"
              title={`Average rating across ${theme.rating_count} attributed reviews carrying a numeric rating`}
            >
              ★ {theme.avg_rating.toFixed(1)}
            </Badge>
          )}
          {typeof theme.localized_share === 'number' && (
            <Badge
              variant={theme.localized_share >= 0.4 ? 'success' : theme.localized_share >= 0.15 ? 'info' : 'secondary'}
              className="rounded-full"
              title="Fraction of this theme's reviews from the selected bike"
            >
              {Math.round(theme.localized_share * 100)}% this bike
            </Badge>
          )}
          <SentimentBadge s={theme.sentiment} />
          <span className="text-xs text-muted-foreground">{theme.mention_count} mentions</span>
        </div>
      </div>

      {/* Keywords */}
      <div className="flex flex-wrap gap-1.5">
        {theme.keywords.map(kw => (
          <Badge key={kw} variant="secondary" className="rounded-full">
            {kw}
          </Badge>
        ))}
      </div>

      {/* Quotes */}
      {theme.example_quotes.length > 0 && (
        <div className="space-y-1.5">
          {(expanded ? theme.example_quotes : theme.example_quotes.slice(0, 1)).map((q, i) => (
            <blockquote
              key={i}
              className="text-xs text-muted-foreground italic border-l-2 border-border pl-3 leading-relaxed"
            >
              "{q.length > 160 ? q.slice(0, 157) + '…' : q}"
            </blockquote>
          ))}
          {theme.example_quotes.length > 1 && (
            <Button
              variant="link"
              size="sm"
              className="h-auto p-0 text-xs"
              onClick={() => setExpanded(e => !e)}
            >
              {expanded ? 'Show less' : `+ ${theme.example_quotes.length - 1} more quote(s)`}
            </Button>
          )}
        </div>
      )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Main ThemesTab
// ---------------------------------------------------------------------------
// KNOWN_BRAND_IDS used for prefix matching when deriving the brand from a
// bike id. Longest first so 'royal-enfield' beats 'royal'.
const KNOWN_BRAND_IDS = [
  'royal-enfield', 'harley-davidson',
  'yamaha', 'honda', 'hero', 'bajaj', 'tvs', 'suzuki', 'ktm',
  'aprilia', 'kawasaki', 'triumph', 'ducati', 'bmw', 'husqvarna',
] as const

function brandPrefix(bikeId: string): string | null {
  for (const b of KNOWN_BRAND_IDS) {
    if (bikeId === b || bikeId.startsWith(b + '-')) return b
  }
  return null
}

export function ThemesTab() {
  const { selectedBikeId, selectedBrandId } = useSelectedBike()
  const isBrandMode = selectedBikeId === null

  // The Themes API is bike-keyed even when we're running a brand-pool
  // analysis (the result needs SOME bike to be saved against). When the
  // user is in All mode, fall back to the first bike in the brand that
  // has reviews — typically the most popular bike of that brand.
  const { data: allBikes = [] } = useQuery({ queryKey: ['bikes'], queryFn: fetchBikes })
  const effectiveBikeId = useMemo(() => {
    if (selectedBikeId) return selectedBikeId
    if (!selectedBrandId) return null
    const candidates = allBikes.filter(b => brandPrefix(b.id) === selectedBrandId)
    const withReviews = candidates.find(b => (b as { has_reviews?: boolean }).has_reviews)
    return (withReviews?.id) ?? candidates[0]?.id ?? null
  }, [selectedBikeId, selectedBrandId, allBikes])

  const [method, setMethod] = useState<Method>('keyword')
  // In brand mode the pool is forced to 'brand' (no choice to make); in
  // bike mode the user picks via the toggle below.
  const [bikePoolScope, setBikePoolScope] = useState<PoolScope>('bike')
  const poolScope: PoolScope = isBrandMode ? 'brand' : bikePoolScope
  const setPoolScope = (s: PoolScope) => setBikePoolScope(s)
  const [nClusters, setNClusters] = useState(6)
  const [llmBackend, setLlmBackend] = useState('claude')
  const [llmNaming, setLlmNaming] = useState(true)  // BERTopic — refine names with Mistral
  // Merged (defaults ⊕ user overrides) keyword map, populated by KeywordEditor.
  const [keywordsMap, setKeywordsMap] = useState<KeywordMap | null>(null)

  const [hw, setHw] = useState<HardwareReport | null>(null)
  const [hwLoading, setHwLoading] = useState(true)

  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<ThemesResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Load hardware info once
  useEffect(() => {
    fetchHardware()
      .then(setHw)
      .catch(() => {})
      .finally(() => setHwLoading(false))
  }, [])

  // Load last result whenever the effective bike (per-bike or brand-derived) changes
  useEffect(() => {
    setResult(null)
    setError(null)
    if (!effectiveBikeId) return
    fetchThemes(effectiveBikeId)
      .then(r => {
        if (r.themes) setResult(r)
      })
      .catch(() => {})
  }, [effectiveBikeId])

  function stopPolling() {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  async function startAnalysis() {
    setError(null)
    setRunning(true)
    const config: Record<string, unknown> =
      method === 'tfidf'
        ? { n_clusters: nClusters }
        : method === 'llm'
        ? { backend: llmBackend }
        : method === 'semantic'
        ? {}
        : method === 'bertopic'
        ? { llm_naming: llmNaming }
        : keywordsMap // method === 'keyword'
        ? { keywords: keywordsMap }
        : {}

    if (!effectiveBikeId) {
      setError('Pick a model (or a brand with at least one bike) to run themes')
      setRunning(false)
      return
    }
    try {
      await triggerThemesAnalysis(effectiveBikeId, method, config, poolScope)
    } catch (e) {
      setError(String(e))
      setRunning(false)
      return
    }

    // Poll status
    pollRef.current = setInterval(async () => {
      try {
        const status = await fetchThemesStatus(effectiveBikeId)
        if (!status.running) {
          stopPolling()
          setRunning(false)
          const latest = await fetchThemes(effectiveBikeId)
          if (latest.themes) {
            setResult(latest)
          } else if (latest.error) {
            setError(latest.error)
          }
        }
      } catch {
        stopPolling()
        setRunning(false)
      }
    }, 2000)
  }

  useEffect(() => () => stopPolling(), [])

  function refreshHw() {
    fetchHardware()
      .then(setHw)
      .catch(() => {})
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------
  return (
    <div className="space-y-6">

      {/* Hardware card */}
      <div>
        <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
          Your Hardware
        </h2>
        {hwLoading ? (
          <Card className="h-24 animate-pulse" />
        ) : hw ? (
          <HardwareCard hw={hw} onPull={refreshHw} />
        ) : (
          <Card className="py-3">
            <CardContent className="text-sm text-muted-foreground">
              Could not detect hardware. Is the backend running?
            </CardContent>
          </Card>
        )}
      </div>

      {/* Method picker */}
      <div>
        <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
          Analysis Method
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-3">
          {METHODS.map(m => (
            <MethodCard
              key={m.id}
              method={m}
              selected={method === m.id}
              onClick={() => setMethod(m.id)}
            />
          ))}
        </div>
      </div>

      {/* Config panel */}
      <div>
        <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
          Configuration
        </h2>
        <ConfigPanel
          method={method}
          hw={hw}
          nClusters={nClusters}
          setNClusters={setNClusters}
          llmBackend={llmBackend}
          setLlmBackend={setLlmBackend}
          llmNaming={llmNaming}
          setLlmNaming={setLlmNaming}
          onKeywordsChange={setKeywordsMap}
        />
      </div>

      {/* Pool-scope toggle: bike-only vs brand-wide. Hidden in brand mode
          since the pool is always brand-wide and there's no per-bike target
          to localize against. */}
      {!isBrandMode && (
      <div>
        <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
          Review Pool
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {([
            {
              id: 'bike' as PoolScope,
              label: 'Just this bike',
              detail: 'Cluster only the selected bike\'s reviews. Best for popular bikes with plenty of feedback.',
            },
            {
              id: 'brand' as PoolScope,
              label: 'Brand-wide pool',
              detail: 'Cluster all reviews of every bike from this brand. Niche bikes inherit themes from siblings; each theme shows a "share of this bike" badge.',
            },
          ]).map(opt => (
            <button
              key={opt.id}
              type="button"
              onClick={() => setPoolScope(opt.id)}
              className={`text-left rounded-xl border px-4 py-3 transition-colors ${
                poolScope === opt.id
                  ? 'border-primary bg-primary/10'
                  : 'border-border bg-card hover:bg-accent'
              }`}
            >
              <div className="font-medium text-sm">{opt.label}</div>
              <div className="text-xs text-muted-foreground mt-1 leading-relaxed">
                {opt.detail}
              </div>
            </button>
          ))}
        </div>
      </div>
      )}

      {isBrandMode && (
        <div className="text-xs text-muted-foreground border-l-2 border-primary/40 pl-3 leading-relaxed">
          You're in <strong className="text-foreground">All models</strong> mode — themes are clustered across every bike in the brand. Pick a specific model from the dropdown to localize and see "% this bike" badges per theme.
        </div>
      )}

      {/* Run button */}
      <Button
        onClick={startAnalysis}
        disabled={running}
        size="lg"
        className="w-full"
      >
        {running ? <Loader2 className="animate-spin" /> : <Sparkles />}
        {running
          ? 'Analysing…'
          : `Run ${METHODS.find(m => m.id === method)?.label ?? ''} Analysis${poolScope === 'brand' ? ' (brand-wide)' : ''}`}
      </Button>

      {/* Error */}
      {error && (
        <div className="bg-destructive/10 border border-destructive/40 text-destructive rounded-xl px-4 py-3 text-sm">
          {error}
        </div>
      )}

      {/* Results */}
      {result?.themes && result.themes.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
              Themes — {result.method}
              {result.run_at && (
                <span className="ml-2 font-normal normal-case text-slate-500">
                  · {new Date(result.run_at).toLocaleString()}
                </span>
              )}
            </h2>
            <span className="text-xs text-slate-500">{result.themes.length} themes found</span>
          </div>

          {/* Sentiment summary bar */}
          <div className="flex gap-2 text-xs">
            {(['positive', 'negative', 'mixed'] as const).map(s => {
              const count = result.themes!.filter(t => t.sentiment === s).length
              if (!count) return null
              const colors: Record<string, string> = {
                positive: 'text-emerald-400',
                negative: 'text-red-400',
                mixed: 'text-amber-400',
              }
              return (
                <span key={s} className={`${colors[s]}`}>
                  {count} {s}
                </span>
              )
            })}
          </div>

          {/* Quality metrics pills */}
          {result.metrics && (
            <div className="flex flex-wrap gap-2 text-xs">
              {result.metrics.npmi !== null && (
                <Badge
                  variant={result.metrics.npmi >= 0.3 ? 'success' : result.metrics.npmi >= 0.1 ? 'info' : 'warning'}
                  className="rounded-full"
                  title="Normalised Pointwise Mutual Information — average pairwise coherence of theme keywords (>0.3 sharp, 0.1-0.3 decent, <0.1 noisy)"
                >
                  coherence (NPMI) {result.metrics.npmi.toFixed(2)}
                </Badge>
              )}
              {result.metrics.theme_diversity !== null && (
                <Badge
                  variant={result.metrics.theme_diversity >= 0.7 ? 'success' : 'info'}
                  className="rounded-full"
                  title="Fraction of unique tokens across all themes — high values mean themes don't overlap"
                >
                  diversity {(result.metrics.theme_diversity * 100).toFixed(0)}%
                </Badge>
              )}
              <Badge variant="secondary" className="rounded-full" title="Reviews fed into the clustering">
                {result.metrics.n_reviews} reviews
              </Badge>
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {result.themes.map((t, i) => (
              <ThemeCard key={t.name} theme={t} rank={i + 1} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
