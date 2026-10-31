import type { KeywordMap } from '../../api/themesApi'
import type { HardwareReport } from '../../types/themes'
import { KeywordEditor } from '../KeywordEditor'
import { Card, CardContent } from '../ui/card'
import type { Method } from './methods'

export function ConfigPanel({
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
