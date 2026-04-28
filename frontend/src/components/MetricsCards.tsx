import { AlertTriangle, TrendingUp } from 'lucide-react'
import type { ForecastResult } from '../api/salesApi'
import type { Metrics, SalesDataPoint } from '../types/sales'
import { formatMonth } from '../utils/format'
import { Card, CardContent } from './ui/card'

interface Props {
  metrics: Metrics | null
  sales: SalesDataPoint[]
  launchMonth?: string | null
  // Optional Prophet payload — when present, renders a 4th "Next month
  // forecast" tile alongside the existing three.
  forecast?: ForecastResult | null
}

function MetricCard({
  label,
  value,
  sub,
  warning,
}: {
  label: string
  value: string
  sub?: string
  warning?: string
}) {
  return (
    <Card className="py-5 gap-1">
      <CardContent className="flex flex-col gap-1">
        <p className="text-muted-foreground text-xs font-medium uppercase tracking-wider">
          {label}
        </p>
        <p className="text-3xl font-bold text-foreground">{value}</p>
        {sub && <p className="text-muted-foreground text-sm">{sub}</p>}
        {warning && (
          <p className="text-amber-400/90 text-xs mt-1 flex items-center gap-1.5">
            <AlertTriangle className="size-3" />
            <span>{warning}</span>
          </p>
        )}
      </CardContent>
    </Card>
  )
}

// Display-only delta. Hides the percentage when the prior-month value is too
// small to be a meaningful denominator (≤500) — in that case the percentage
// just creates visual noise like "+53344%" that screams "broken data".
function deltaText(current: number, prev: number | undefined): string {
  if (prev === undefined) return ''
  if (prev <= 500) return 'prior month value too low to compare'
  const pct = ((current - prev) / prev) * 100
  // Cap the displayed value so we don't print silly numbers
  const capped = Math.max(-999, Math.min(999, pct))
  const sign = capped >= 0 ? '+' : ''
  return `${sign}${capped.toFixed(1)}% vs prior month`
}

// Returns a YYYY-MM string for the current calendar month.
function currentYearMonth(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

// Months between two YYYY-MM strings (a < b returns positive).
function monthsBetween(a: string, b: string): number {
  const [ay, am] = a.split('-').map(Number)
  const [by, bm] = b.split('-').map(Number)
  return (by - ay) * 12 + (bm - am)
}

function stalenessLabel(latestMonth: string): string | undefined {
  const gap = monthsBetween(latestMonth, currentYearMonth())
  if (gap <= 1) return undefined
  if (gap === 2) return '1 month behind'
  return `${gap} months behind`
}

export function MetricsCards({ metrics, sales, launchMonth, forecast }: Props) {
  // 4-tile grid when a forecast is present, 3 otherwise.
  const nextForecast = forecast?.forecast?.[0] ?? null
  const cols = nextForecast ? 'sm:grid-cols-2 lg:grid-cols-4' : 'sm:grid-cols-3'

  if (!metrics) {
    return (
      <div className={`grid grid-cols-1 ${cols} gap-4`}>
        {Array.from({ length: nextForecast ? 4 : 3 }, (_, i) => (
          <Card key={i} className="h-24 animate-pulse" />
        ))}
      </div>
    )
  }

  const latestIdx = sales.findIndex(s => s.month === metrics.latest_month?.month)
  const prevUnits = latestIdx > 0 ? sales[latestIdx - 1].units_sold : undefined

  const latestSub = metrics.latest_month
    ? [
        formatMonth(metrics.latest_month.month),
        prevUnits !== undefined ? deltaText(metrics.latest_month.units_sold, prevUnits) : '',
      ]
        .filter(Boolean)
        .join(' · ')
    : undefined

  const stale = metrics.latest_month ? stalenessLabel(metrics.latest_month.month) : undefined

  // Forecast-tile sub copy: month label + delta vs. last observed month.
  let nextForecastSub: string | undefined
  if (nextForecast) {
    const parts: string[] = [formatMonth(nextForecast.month)]
    if (metrics.latest_month) {
      const d = nextForecast.yhat - metrics.latest_month.units_sold
      const sign = d >= 0 ? '+' : ''
      parts.push(`${sign}${Math.round(d).toLocaleString()} vs latest`)
    }
    parts.push(
      `range ${Math.round(nextForecast.yhat_lower).toLocaleString()}–` +
      `${Math.round(nextForecast.yhat_upper).toLocaleString()}`,
    )
    nextForecastSub = parts.join(' · ')
  }

  return (
    <div className={`grid grid-cols-1 ${cols} gap-4`}>
      <MetricCard
        label="Latest Month"
        value={metrics.latest_month ? metrics.latest_month.units_sold.toLocaleString() : '—'}
        sub={latestSub}
        warning={stale}
      />
      <MetricCard
        label="Peak Month"
        value={metrics.peak_month ? metrics.peak_month.units_sold.toLocaleString() : '—'}
        sub={metrics.peak_month ? formatMonth(metrics.peak_month.month) : undefined}
      />
      <MetricCard
        label="Total Tracked"
        value={metrics.total_units.toLocaleString()}
        sub={`${metrics.months_tracked} month${metrics.months_tracked !== 1 ? 's' : ''} tracked${
          launchMonth ? ` · since ${formatMonth(launchMonth)}` : ''
        }`}
      />
      {nextForecast && (
        <Card className="py-5 gap-1 border-violet-500/30 bg-violet-500/5">
          <CardContent className="flex flex-col gap-1">
            <p className="text-violet-300/80 text-xs font-medium uppercase tracking-wider flex items-center gap-1.5">
              <TrendingUp className="size-3" />
              Next Month Forecast
            </p>
            <p className="text-3xl font-bold text-foreground">
              {Math.round(nextForecast.yhat).toLocaleString()}
            </p>
            {nextForecastSub && (
              <p className="text-muted-foreground text-sm">{nextForecastSub}</p>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
