import { ExternalLink } from 'lucide-react'

import type { SeriesHistoryPoint } from '../types/sales'
import { formatMonth } from '../utils/format'
import { Badge } from './ui/badge'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from './ui/dialog'

interface Props {
  point: SeriesHistoryPoint | null
  displayName?: string
  onClose: () => void
}

const SOURCE_LABELS: Record<string, string> = {
  rushlane: 'RushLane',
  autopunditz: 'AutoPunditz',
  fada: 'FADA Retail',
  fada_retail: 'FADA Retail',
  bikedekho: 'BikeDekho',
  ht_auto: 'HT Auto',
  autocarpro_ocr: 'AutoCarPro (OCR)',
}

function summary(point: SeriesHistoryPoint): {
  min: number
  max: number
  median: number
  spreadPct: number | null
} {
  const vals = point.sources.map(s => s.units_sold).sort((a, b) => a - b)
  const min = vals[0] ?? 0
  const max = vals[vals.length - 1] ?? 0
  const median = point.units
  const spreadPct = median > 0 ? ((max - min) / median) * 100 : null
  return { min, max, median, spreadPct }
}

/**
 * Modal opened by clicking a bar in the unified Sales chart. Shows the
 * per-source values that contributed to that month's expected (median)
 * value, plus a small spread summary so the reader can eyeball how much
 * the sources disagree.
 */
export function SourceDistributionDialog({ point, displayName, onClose }: Props) {
  const open = point !== null

  return (
    <Dialog open={open} onOpenChange={v => { if (!v) onClose() }}>
      <DialogContent className="max-w-md">
        {point && (
          <>
            <DialogHeader>
              <DialogTitle className="text-base">
                {displayName ?? 'Selected bike'} · {formatMonth(point.month)}
              </DialogTitle>
            </DialogHeader>

            {point.imputed ? (
              <div className="text-sm text-muted-foreground">
                <p className="mb-1">
                  This month was <strong>imputed</strong> — no source reported a
                  value for it. The chart fills it via{' '}
                  <code>{point.impute_method ?? 'unknown'}</code> based on
                  surrounding observed months.
                </p>
                <p>
                  Imputed value:{' '}
                  <strong className="text-foreground">
                    {Math.round(point.units).toLocaleString()}
                  </strong>{' '}
                  units.
                </p>
              </div>
            ) : (
              <DistributionBody point={point} />
            )}
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}

function DistributionBody({ point }: { point: SeriesHistoryPoint }) {
  const { min, max, median, spreadPct } = summary(point)
  const single = point.n_sources === 1

  return (
    <div className="space-y-4">
      {/* Headline */}
      <div className="flex items-baseline gap-3 flex-wrap">
        <div>
          <p className="text-xs text-muted-foreground uppercase tracking-wider">
            Expected value
          </p>
          <p className="text-3xl font-bold text-foreground">
            {Math.round(median).toLocaleString()}
          </p>
        </div>
        {!single && (
          <Badge variant="secondary" className="rounded-full">
            median across {point.n_sources} sources
          </Badge>
        )}
        {single && (
          <Badge variant="secondary" className="rounded-full">
            1 source · single observation
          </Badge>
        )}
      </div>

      {/* Spread */}
      {!single && (
        <div className="grid grid-cols-3 gap-2 text-xs">
          <div className="border rounded-md p-2">
            <p className="text-muted-foreground">min</p>
            <p className="text-sm font-medium">{Math.round(min).toLocaleString()}</p>
          </div>
          <div className="border rounded-md p-2">
            <p className="text-muted-foreground">max</p>
            <p className="text-sm font-medium">{Math.round(max).toLocaleString()}</p>
          </div>
          <div className="border rounded-md p-2">
            <p className="text-muted-foreground">σ</p>
            <p className="text-sm font-medium">
              {point.stddev != null ? Math.round(point.stddev).toLocaleString() : '—'}
            </p>
          </div>
        </div>
      )}
      {!single && spreadPct != null && (
        <p className="text-xs text-muted-foreground">
          Sources disagree by{' '}
          <strong className="text-foreground">±{spreadPct.toFixed(1)}%</strong>{' '}
          of the median. Below {'<'}10% is broadly consistent; {'>'}25% suggests
          a real divergence (often wholesale vs. retail).
        </p>
      )}

      {/* Per-source breakdown */}
      <div>
        <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
          Per source
        </p>
        <div className="space-y-1.5">
          {[...point.sources]
            .sort((a, b) => b.units_sold - a.units_sold)
            .map(s => (
              <div
                key={`${s.source}-${s.units_sold}`}
                className="flex items-center justify-between gap-3 text-sm border-l-2 border-border pl-3"
              >
                <div className="flex items-center gap-2 min-w-0">
                  <Badge variant="outline" className="rounded-full">
                    {SOURCE_LABELS[s.source] ?? s.source}
                  </Badge>
                  {s.source_url && (
                    <a
                      href={s.source_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-xs text-primary hover:underline inline-flex items-center gap-1"
                    >
                      source <ExternalLink className="size-3" />
                    </a>
                  )}
                </div>
                <span className="font-mono tabular-nums">
                  {s.units_sold.toLocaleString()}
                </span>
              </div>
            ))}
        </div>
      </div>

      {/* Anomaly note */}
      {point.anomaly && (
        <p className="text-xs text-amber-400/90 border-t pt-3">
          ⚠ Flagged as a historical anomaly — z-score{' '}
          {point.anomaly.z_score >= 0 ? '+' : ''}
          {point.anomaly.z_score.toFixed(1)}σ vs. trailing 12-month norm.
        </p>
      )}
    </div>
  )
}
