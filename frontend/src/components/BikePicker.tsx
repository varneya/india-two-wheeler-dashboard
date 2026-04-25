import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  fetchBrandModels,
  fetchBrands,
  triggerBikeRefresh,
  type BrandModel,
} from '../api/bikesApi'
import { useSelectedBike } from '../context/SelectedBike'

function formatUnits(n: number): string {
  if (n >= 100_000) return `${(n / 100_000).toFixed(1)}L`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  return String(n)
}

function brandIdFromBikeId(bikeId: string, brandIds: string[]): string | null {
  for (const bId of brandIds) {
    if (bikeId === bId || bikeId.startsWith(bId + '-')) return bId
  }
  return null
}

// ---------------------------------------------------------------------------
// Brand dropdown
// ---------------------------------------------------------------------------

function BrandDropdown({
  brands,
  selectedId,
  onPick,
}: {
  brands: ReturnType<typeof useBrands>['brands']
  selectedId: string | null
  onPick: (id: string) => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    if (open) document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [open])

  const selected = brands.find(b => b.id === selectedId)

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-2 bg-card hover:bg-secondary border border-border rounded-xl px-4 py-2 transition-colors min-w-[180px]"
      >
        <div className="text-left flex-1 min-w-0">
          <p className="text-[10px] text-muted-foreground/70 uppercase tracking-wider">Brand</p>
          <p className="text-foreground font-semibold leading-tight truncate">
            {selected?.display ?? 'Choose brand'}
          </p>
        </div>
        <svg
          className={`w-4 h-4 text-muted-foreground transition-transform ${open ? 'rotate-180' : ''}`}
          fill="none" stroke="currentColor" viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <div className="absolute z-30 left-0 top-full mt-2 w-[260px] max-h-[480px] overflow-y-auto bg-card border border-border rounded-xl shadow-2xl py-1">
          {brands.map(b => (
            <button
              key={b.id}
              onClick={() => { onPick(b.id); setOpen(false) }}
              className={`w-full flex items-center gap-3 px-3 py-2 text-left transition-colors ${
                selectedId === b.id ? 'bg-primary/15' : 'hover:bg-accent/50'
              }`}
            >
              <div className="flex-1 min-w-0">
                <p className="text-sm text-foreground">{b.display}</p>
                <p className="text-xs text-muted-foreground">
                  {b.db_bike_count} of {b.model_count} models with data
                </p>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Model dropdown — populated based on selected brand
// ---------------------------------------------------------------------------

function ModelDropdown({
  models,
  selectedId,
  onPick,
  loading,
}: {
  models: BrandModel[]
  selectedId: string
  onPick: (id: string) => void
  loading: boolean
}) {
  const [open, setOpen] = useState(false)
  const [filter, setFilter] = useState('')
  const ref = useRef<HTMLDivElement>(null)
  const qc = useQueryClient()

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    if (open) document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [open])

  const selected = models.find(m => m.id === selectedId)

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase()
    if (!q) return models
    return models.filter(m => m.canonical.toLowerCase().includes(q))
  }, [filter, models])

  // Group: with data first, then catalogue-only
  const withData = filtered.filter(m => m.in_db)
  const empty = filtered.filter(m => !m.in_db)

  async function fetchAndPick(modelId: string) {
    const m = models.find(x => x.id === modelId)
    onPick(modelId)
    setOpen(false)
    setFilter('')
    if (m && !m.in_db) {
      // Catalogue-only model — kick a single-bike refresh in the background
      try {
        await triggerBikeRefresh(modelId)
        qc.invalidateQueries({ queryKey: ['bikes'] })
      } catch {/* ignore */}
    }
  }

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(o => !o)}
        disabled={!models.length && !loading}
        className="flex items-center gap-2 bg-card hover:bg-secondary disabled:opacity-50 disabled:cursor-not-allowed border border-border rounded-xl px-4 py-2 transition-colors min-w-[260px]"
      >
        <div className="text-left flex-1 min-w-0">
          <p className="text-[10px] text-muted-foreground/70 uppercase tracking-wider">Model</p>
          <p className="text-foreground font-semibold leading-tight truncate">
            {selected?.canonical ?? (loading ? 'Loading…' : 'Choose model')}
          </p>
          {selected?.in_db && (
            <p className="text-xs text-muted-foreground">
              {selected.months_tracked} months · {formatUnits(selected.total_units)} units
            </p>
          )}
        </div>
        <svg
          className={`w-4 h-4 text-muted-foreground transition-transform ${open ? 'rotate-180' : ''}`}
          fill="none" stroke="currentColor" viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <div className="absolute z-30 left-0 top-full mt-2 w-[360px] max-h-[480px] flex flex-col bg-card border border-border rounded-xl shadow-2xl">
          <div className="p-3 border-b border-border">
            <input
              autoFocus
              type="text"
              placeholder="Filter models…"
              value={filter}
              onChange={e => setFilter(e.target.value)}
              className="w-full bg-background text-foreground placeholder-muted-foreground rounded-lg px-3 py-2 text-sm outline-none border border-border focus:border-primary"
            />
          </div>
          <div className="overflow-y-auto py-1">
            {withData.length > 0 && (
              <div className="mb-1">
                <p className="text-[10px] text-muted-foreground/70 uppercase tracking-wider px-3 py-1">
                  With sales data
                </p>
                {withData.map(m => (
                  <button
                    key={m.id}
                    onClick={() => fetchAndPick(m.id)}
                    className={`w-full flex items-center gap-3 px-3 py-2 text-left transition-colors ${
                      selectedId === m.id ? 'bg-primary/15' : 'hover:bg-accent/50'
                    }`}
                  >
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-foreground truncate">{m.canonical}</p>
                      <p className="text-xs text-muted-foreground">
                        {m.months_tracked} months tracked
                        {m.has_reviews ? ' · reviews' : ''}
                      </p>
                    </div>
                    <span className="text-xs text-muted-foreground font-mono tabular-nums shrink-0">
                      {formatUnits(m.total_units)}
                    </span>
                  </button>
                ))}
              </div>
            )}
            {empty.length > 0 && (
              <div>
                <p className="text-[10px] text-muted-foreground/70 uppercase tracking-wider px-3 py-1">
                  Catalogue only (no data scraped yet)
                </p>
                {empty.map(m => (
                  <button
                    key={m.id}
                    onClick={() => fetchAndPick(m.id)}
                    className={`w-full flex items-center gap-3 px-3 py-2 text-left text-muted-foreground transition-colors ${
                      selectedId === m.id ? 'bg-primary/15' : 'hover:bg-accent/50'
                    }`}
                  >
                    <p className="text-sm flex-1">{m.canonical}</p>
                    <span className="text-xs shrink-0">—</span>
                  </button>
                ))}
              </div>
            )}
            {filtered.length === 0 && (
              <p className="text-center text-muted-foreground/70 text-sm py-8">
                No models in catalogue.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Hook: fetch brands
// ---------------------------------------------------------------------------

function useBrands() {
  const q = useQuery({
    queryKey: ['brands'],
    queryFn: fetchBrands,
    refetchInterval: 5000,
  })
  return { brands: q.data ?? [], isLoading: q.isLoading }
}

// ---------------------------------------------------------------------------
// Top-level: brand dropdown + model dropdown + discover button
// ---------------------------------------------------------------------------

export function BikePicker() {
  const { selectedBikeId, setSelectedBikeId } = useSelectedBike()
  const { brands } = useBrands()

  const brandIds = useMemo(() => brands.map(b => b.id), [brands])
  const initialBrand = brandIdFromBikeId(selectedBikeId, brandIds) || brands[0]?.id || null

  const [brandId, setBrandId] = useState<string | null>(initialBrand)
  // Keep brand in sync if selectedBikeId changes externally
  useEffect(() => {
    const inferred = brandIdFromBikeId(selectedBikeId, brandIds)
    if (inferred && inferred !== brandId) setBrandId(inferred)
  }, [selectedBikeId, brandIds])

  const modelsQ = useQuery({
    queryKey: ['brandModels', brandId],
    queryFn: () => fetchBrandModels(brandId!),
    enabled: !!brandId,
    refetchInterval: 5000,
  })

  function pickBrand(id: string) {
    setBrandId(id)
    // Auto-select the first bike in the brand that has data, else the first model
    fetchBrandModels(id).then(models => {
      const next = models.find(m => m.in_db) ?? models[0]
      if (next) setSelectedBikeId(next.id)
    })
  }

  function pickModel(id: string) {
    setSelectedBikeId(id)
  }

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <BrandDropdown brands={brands} selectedId={brandId} onPick={pickBrand} />
      <ModelDropdown
        models={modelsQ.data ?? []}
        selectedId={selectedBikeId}
        onPick={pickModel}
        loading={modelsQ.isLoading}
      />
    </div>
  )
}
