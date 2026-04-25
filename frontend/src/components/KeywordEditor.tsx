import { useQuery } from '@tanstack/react-query'
import { Plus, RotateCcw, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { fetchKeywordDefaults, type KeywordMap } from '../api/themesApi'
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from './ui/accordion'
import { Badge } from './ui/badge'
import { Button } from './ui/button'
import { Card, CardContent } from './ui/card'
import { Input } from './ui/input'

const STORAGE_KEY = 'keyword-overrides-v1'

interface Props {
  /** Receives the merged (defaults ⊕ overrides) keyword map whenever it changes,
   *  so the parent can include it in the analysis request. */
  onChange?: (merged: KeywordMap) => void
}

function readOverrides(): KeywordMap {
  if (typeof window === 'undefined') return {}
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? (parsed as KeywordMap) : {}
  } catch {
    return {}
  }
}

function writeOverrides(map: KeywordMap) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(map))
  } catch {/* ignore */}
}

export function KeywordEditor({ onChange }: Props) {
  const { data: defaults } = useQuery({
    queryKey: ['keyword-defaults'],
    queryFn: fetchKeywordDefaults,
    staleTime: Infinity, // defaults rarely change
  })
  const [overrides, setOverrides] = useState<KeywordMap>(readOverrides)
  const [drafts, setDrafts] = useState<Record<string, string>>({})

  // Merged map = override-if-present-else-default
  const merged = useMemo<KeywordMap>(() => {
    if (!defaults) return overrides
    const out: KeywordMap = {}
    for (const theme of Object.keys(defaults)) {
      out[theme] = overrides[theme] ?? defaults[theme]
    }
    return out
  }, [defaults, overrides])

  // Notify parent on every change
  useEffect(() => {
    if (defaults) onChange?.(merged)
  }, [merged, defaults, onChange])

  if (!defaults) {
    return (
      <Card>
        <CardContent className="text-sm text-muted-foreground">Loading keyword buckets…</CardContent>
      </Card>
    )
  }

  function setBucket(theme: string, next: string[]) {
    setOverrides(prev => {
      const updated = { ...prev, [theme]: next }
      writeOverrides(updated)
      return updated
    })
  }

  function resetBucket(theme: string) {
    setOverrides(prev => {
      const { [theme]: _, ...rest } = prev
      writeOverrides(rest)
      return rest
    })
    setDrafts(d => ({ ...d, [theme]: '' }))
  }

  function resetAll() {
    setOverrides({})
    writeOverrides({})
    setDrafts({})
  }

  function addKeyword(theme: string) {
    const draft = (drafts[theme] || '').trim()
    if (!draft) return
    const current = merged[theme] ?? []
    if (current.some(k => k.toLowerCase() === draft.toLowerCase())) {
      // already present — clear input and bail
      setDrafts(d => ({ ...d, [theme]: '' }))
      return
    }
    setBucket(theme, [...current, draft])
    setDrafts(d => ({ ...d, [theme]: '' }))
  }

  function removeKeyword(theme: string, kw: string) {
    const current = merged[theme] ?? []
    const next = current.filter(k => k !== kw)
    setBucket(theme, next)
  }

  const customisedCount = Object.keys(overrides).length
  const totalKeywords = Object.values(merged).reduce((s, arr) => s + arr.length, 0)

  return (
    <Card className="gap-0 py-0 overflow-hidden">
      <CardContent className="px-5 py-4 border-b border-border">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div>
            <p className="text-sm font-medium text-foreground">Keyword buckets</p>
            <p className="text-xs text-muted-foreground mt-0.5">
              {Object.keys(defaults).length} themes · {totalKeywords} keywords matched against review text.
              {customisedCount > 0 && (
                <>
                  {' '}
                  <span className="text-amber-400">
                    {customisedCount} bucket{customisedCount === 1 ? '' : 's'} customised
                  </span>
                </>
              )}
            </p>
          </div>
          {customisedCount > 0 && (
            <Button variant="ghost" size="sm" onClick={resetAll}>
              <RotateCcw />
              Reset all
            </Button>
          )}
        </div>
      </CardContent>

      <Accordion type="multiple" className="px-5">
        {Object.entries(defaults).map(([theme, defaultKws]) => {
          const current = merged[theme] ?? defaultKws
          const customised = !!overrides[theme]
          return (
            <AccordionItem key={theme} value={theme}>
              <AccordionTrigger>
                <div className="flex items-center gap-2 min-w-0">
                  <span className="truncate">{theme}</span>
                  <Badge variant="secondary" className="rounded-full">
                    {current.length}
                  </Badge>
                  {customised && (
                    <Badge variant="warning" className="rounded-full">
                      edited
                    </Badge>
                  )}
                </div>
              </AccordionTrigger>
              <AccordionContent>
                <div className="space-y-3">
                  {/* Existing keyword chips */}
                  <div className="flex flex-wrap gap-1.5">
                    {current.length === 0 ? (
                      <p className="text-xs text-muted-foreground italic">
                        No keywords — this bucket is disabled.
                      </p>
                    ) : (
                      current.map(kw => (
                        <Badge
                          key={kw}
                          variant="secondary"
                          className="gap-1 pr-1"
                        >
                          <span>{kw}</span>
                          <button
                            type="button"
                            onClick={() => removeKeyword(theme, kw)}
                            aria-label={`Remove "${kw}"`}
                            className="hover:bg-destructive/20 hover:text-destructive rounded p-0.5 transition-colors"
                          >
                            <X className="size-3" />
                          </button>
                        </Badge>
                      ))
                    )}
                  </div>

                  {/* Add input + reset */}
                  <div className="flex items-center gap-2">
                    <form
                      onSubmit={e => { e.preventDefault(); addKeyword(theme) }}
                      className="flex-1 flex items-center gap-2"
                    >
                      <Input
                        value={drafts[theme] ?? ''}
                        onChange={e => setDrafts(d => ({ ...d, [theme]: e.target.value }))}
                        placeholder="Add keyword (Enter to commit)…"
                        className="h-8 text-xs"
                      />
                      <Button
                        type="submit"
                        size="sm"
                        variant="secondary"
                        disabled={!drafts[theme]?.trim()}
                      >
                        <Plus />
                        Add
                      </Button>
                    </form>
                    {customised && (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => resetBucket(theme)}
                        title="Reset this bucket to defaults"
                      >
                        <RotateCcw />
                        Reset
                      </Button>
                    )}
                  </div>
                </div>
              </AccordionContent>
            </AccordionItem>
          )
        })}
      </Accordion>
    </Card>
  )
}
