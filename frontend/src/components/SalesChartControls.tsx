import { useState } from 'react'
import {
  ChevronDown,
  Info,
  Loader2,
  RefreshCw,
  Sparkles,
  TrendingUp,
} from 'lucide-react'

import type { ForecastResult } from '../api/salesApi'
import type { SalesSeriesResponse } from '../types/sales'
import { Badge } from './ui/badge'
import { Button } from './ui/button'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from './ui/collapsible'

interface Props {
  series: SalesSeriesResponse | null
  forecast: ForecastResult | null
  showForecast: boolean
  setShowForecast: (v: boolean) => void
  horizon: number
  setHorizon: (v: number) => void
  forecastFitting: boolean
  canForecast: boolean
  observedCount: number
  refit: () => void
}

const HORIZON_OPTIONS = [3, 6, 9, 12, 18, 24]

/**
 * Chart toolbar with two visual states:
 *
 *   1. Forecast OFF (default): one prominent CTA — "Show forecast". Nothing
 *      else above the chart so first-time visitors aren't faced with stats
 *      jargon.
 *   2. Forecast ON: compact toolbar (horizon dropdown, Re-fit, Hide) + a
 *      tucked-away "What does this mean?" expander that reveals plain-
 *      English explanations of the technical details (estimated months,
 *      forecast range, low-confidence warning).
 *
 * Bare-minimum data context (months of real data, months estimated) is
 * always shown but the wording is friendly — no abbreviations like "mo"
 * or "CI" without the expander to decode them.
 */
export function SalesChartControls({
  series,
  forecast,
  showForecast,
  setShowForecast,
  horizon,
  setHorizon,
  forecastFitting,
  canForecast,
  observedCount,
  refit,
}: Props) {
  const [explainerOpen, setExplainerOpen] = useState(false)
  const imputedCount = series?.history.filter(h => h.imputed).length ?? 0
  const hasData = !!series

  // -------------------------------------------------------------------------
  // State 1: forecast off — calm, single CTA + soft data summary
  // -------------------------------------------------------------------------
  if (!showForecast) {
    return (
      <div className="flex items-center justify-between gap-3 flex-wrap mb-3">
        {hasData && (
          <p className="text-sm text-muted-foreground">
            <span className="text-foreground font-medium">{observedCount}</span>{' '}
            {observedCount === 1 ? 'month' : 'months'} of real data
            {imputedCount > 0 && (
              <>
                {' · '}
                <span className="text-foreground font-medium">{imputedCount}</span>{' '}
                {imputedCount === 1 ? 'month' : 'months'} estimated
              </>
            )}
          </p>
        )}

        {canForecast ? (
          <Button
            onClick={() => setShowForecast(true)}
            disabled={forecastFitting}
            size="sm"
          >
            {forecastFitting ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Sparkles className="size-4" />
            )}
            Show forecast
          </Button>
        ) : hasData ? (
          <span className="text-xs text-muted-foreground">
            Need at least 4 months of data to forecast (have {observedCount}).
          </span>
        ) : null}
      </div>
    )
  }

  // -------------------------------------------------------------------------
  // State 2: forecast on — compact toolbar + collapsible explainer
  // -------------------------------------------------------------------------
  return (
    <div className="flex flex-col gap-2 mb-3">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex flex-wrap gap-2 text-xs items-center">
          {series && (
            <Badge variant="secondary" className="rounded-full">
              {observedCount} {observedCount === 1 ? 'month' : 'months'} of real data
            </Badge>
          )}
          {imputedCount > 0 && (
            <Badge variant="secondary" className="rounded-full">
              {imputedCount} estimated
            </Badge>
          )}
          {forecast && (
            <Badge variant="info" className="rounded-full">
              {forecast.horizon}-month forecast
            </Badge>
          )}
          {forecast?.low_confidence && (
            <Badge variant="destructive" className="rounded-full">
              Low confidence
            </Badge>
          )}
          {forecastFitting && (
            <Badge variant="info" className="rounded-full">
              <Loader2 className="size-3 animate-spin" /> fitting…
            </Badge>
          )}
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <select
            value={horizon}
            onChange={e => setHorizon(parseInt(e.target.value, 10))}
            className="bg-card border border-border rounded-md px-2 py-1 text-sm"
            title="How many months to forecast ahead"
          >
            {HORIZON_OPTIONS.map(h => (
              <option key={h} value={h}>{h} months</option>
            ))}
          </select>
          <Button
            variant="outline"
            size="sm"
            onClick={refit}
            disabled={forecastFitting}
            title="Recompute the forecast on the latest data"
          >
            {forecastFitting ? (
              <Loader2 className="size-3 animate-spin" />
            ) : (
              <RefreshCw className="size-3" />
            )}
            Re-fit
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowForecast(false)}
            title="Return to just the historical chart"
          >
            <TrendingUp className="size-3" />
            Hide forecast
          </Button>
        </div>
      </div>

      {/* Plain-English explainer for non-data audiences */}
      <Collapsible open={explainerOpen} onOpenChange={setExplainerOpen}>
        <CollapsibleTrigger asChild>
          <button
            type="button"
            className="self-start inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            <Info className="size-3.5" />
            What do these mean?
            <ChevronDown
              className={`size-3.5 transition-transform ${
                explainerOpen ? 'rotate-180' : ''
              }`}
            />
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent className="mt-2">
          <div className="rounded-lg border border-border/60 bg-card/50 p-4 text-sm space-y-2.5 text-muted-foreground">
            <p>
              <strong className="text-foreground">Real data</strong> are months
              where a source (AutoPunditz, RushLane) reported an actual
              sales number for this bike.
            </p>
            <p>
              <strong className="text-foreground">Estimated</strong> months are
              gaps where no source reported. We fill them in using the trend of
              the months around them so the forecast model has a continuous
              series to learn from.
            </p>
            <p>
              <strong className="text-foreground">Forecast range</strong> (the
              shaded band) shows where future sales are likely to land. A
              wider band means more uncertainty; a narrow band means the
              recent pattern is very consistent.
            </p>
            {forecast?.low_confidence && (
              <p>
                <strong className="text-foreground">Low confidence</strong>{' '}
                appears when we have less than 12 months of real data for this
                bike. The forecast still works, but seasonality and
                year-over-year trends aren't fully established yet, so the
                numbers can swing more than they will once more data comes in.
              </p>
            )}
            <p>
              <strong className="text-foreground">Unusual jumps and
              drops</strong> highlight months that look very different from
              the surrounding trend — either a launch month, a stock-out, or
              data that may need verification.
            </p>
          </div>
        </CollapsibleContent>
      </Collapsible>
    </div>
  )
}
