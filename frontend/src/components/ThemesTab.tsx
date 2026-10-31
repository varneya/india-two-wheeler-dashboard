import { Loader2, Sparkles } from 'lucide-react'
import { useState } from 'react'
import type { KeywordMap, PoolScope } from '../api/themesApi'
import { useSelectedBike } from '../context/SelectedBike'
import { useEffectiveBikeId } from '../hooks/useEffectiveBikeId'
import { useThemesAnalysis } from '../hooks/useThemesAnalysis'
import { ConfigPanel } from './themes/ConfigPanel'
import { HardwarePanel } from './themes/HardwarePanel'
import { MethodPicker } from './themes/MethodPicker'
import { METHODS, type Method } from './themes/methods'
import { ReviewPoolPicker } from './themes/ReviewPoolPicker'
import { ThemesResults } from './themes/ThemesResults'
import { useThemesHardware } from './themes/useThemesHardware'
import { Button } from './ui/button'

export function ThemesTab() {
  const { selectedBikeId, selectedBrandId } = useSelectedBike()
  const isBrandMode = selectedBikeId === null
  const effectiveBikeId = useEffectiveBikeId(selectedBikeId, selectedBrandId)

  const [method, setMethod] = useState<Method>('keyword')
  // In brand mode the pool is forced to 'brand' (no choice to make); in
  // bike mode the user picks via the toggle below.
  const [bikePoolScope, setBikePoolScope] = useState<PoolScope>('bike')
  const poolScope: PoolScope = isBrandMode ? 'brand' : bikePoolScope
  const [nClusters, setNClusters] = useState(6)
  const [llmBackend, setLlmBackend] = useState('claude')
  const [llmNaming, setLlmNaming] = useState(true)  // BERTopic — refine names with Mistral
  // Merged (defaults ⊕ user overrides) keyword map, populated by KeywordEditor.
  const [keywordsMap, setKeywordsMap] = useState<KeywordMap | null>(null)

  const { hw, hwLoading, hwError, refreshHw } = useThemesHardware()

  const config: Record<string, unknown> =
    method === 'tfidf'
      ? { n_clusters: nClusters }
      : method === 'llm'
      ? { backend: llmBackend }
      : method === 'bertopic'
      ? { llm_naming: llmNaming }
      : method === 'keyword' && keywordsMap
      ? { keywords: keywordsMap }
      : {}

  const { running, result, error, startAnalysis } = useThemesAnalysis({
    bikeId: effectiveBikeId,
    method,
    config,
    poolScope,
  })

  return (
    <div className="space-y-6">
      <HardwarePanel hw={hw} hwLoading={hwLoading} hwError={hwError} onPull={refreshHw} />
      <MethodPicker method={method} onChange={setMethod} />

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

      <ReviewPoolPicker
        isBrandMode={isBrandMode}
        poolScope={poolScope}
        onChange={setBikePoolScope}
      />

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

      <ThemesResults result={result} />
    </div>
  )
}
