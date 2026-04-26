import { Loader2, RefreshCw, Sparkles, TrendingUp } from 'lucide-react'

import type { ForecastResult } from '../api/salesApi'
import type { SalesSeriesResponse } from '../types/sales'
import { Badge } from './ui/badge'
import { Button } from './ui/button'

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
 * Top-of-chart control strip + status pills. Renders:
 *   - n observed / m imputed pills (always, when series is loaded)
 *   - horizon dropdown + Show-forecast toggle (when canForecast)
 *   - Forecast pills + Re-fit button (when forecast is on)
 *   - "Need more data" hint when canForecast=false
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
  const imputedCount = series?.history.filter(h => h.imputed).length ?? 0

  return (
    <div className="flex items-start justify-between gap-3 flex-wrap mb-3">
      {/* Status pills (left) */}
      <div className="flex flex-wrap gap-2 text-xs items-center">
        {series && (
          <Badge variant="secondary" className="rounded-full">
            {observedCount} observed mo
          </Badge>
        )}
        {imputedCount > 0 && (
          <Badge variant="warning" className="rounded-full">
            {imputedCount} imputed
          </Badge>
        )}
        {forecast && showForecast && (
          <>
            <Badge variant="info" className="rounded-full">
              {forecast.horizon}-mo forecast · {Math.round(forecast.interval_width * 100)}% CI
            </Badge>
            {forecast.low_confidence && (
              <Badge variant="destructive" className="rounded-full">
                low confidence — &lt; 12 mo of history
              </Badge>
            )}
          </>
        )}
        {forecastFitting && (
          <Badge variant="info" className="rounded-full">
            <Loader2 className="size-3 animate-spin" /> fitting Prophet…
          </Badge>
        )}
        {!canForecast && series && (
          <span className="text-xs text-muted-foreground">
            Need ≥ 4 observed months for a forecast (have {observedCount}).
          </span>
        )}
      </div>

      {/* Controls (right) */}
      {canForecast && (
        <div className="flex items-center gap-2 flex-wrap">
          <select
            value={horizon}
            onChange={e => setHorizon(parseInt(e.target.value, 10))}
            className="bg-card border border-border rounded-md px-2 py-1 text-sm"
            disabled={!showForecast}
            title={showForecast ? 'Forecast horizon' : 'Turn on the forecast layer to change horizon'}
          >
            {HORIZON_OPTIONS.map(h => (
              <option key={h} value={h}>{h} months</option>
            ))}
          </select>

          {!showForecast ? (
            <Button
              variant="default"
              size="sm"
              onClick={() => setShowForecast(true)}
              disabled={forecastFitting}
            >
              {forecastFitting ? (
                <Loader2 className="size-3 animate-spin" />
              ) : (
                <Sparkles className="size-3" />
              )}
              Run forecast
            </Button>
          ) : (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setShowForecast(false)}
                title="Hide the forecast layer (keeps the cached fit)"
              >
                <TrendingUp className="size-3" />
                Hide forecast
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={refit}
                disabled={forecastFitting}
                title="Re-fit Prophet on the current series"
              >
                {forecastFitting ? (
                  <Loader2 className="size-3 animate-spin" />
                ) : (
                  <RefreshCw className="size-3" />
                )}
                Re-fit
              </Button>
            </>
          )}
        </div>
      )}
    </div>
  )
}
