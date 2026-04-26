import {
  Area,
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { ForecastResult } from '../api/salesApi'
import type { SalesSeriesResponse } from '../types/sales'
import { formatMonth } from '../utils/format'
import { Card, CardContent } from './ui/card'

interface Props {
  // Canonical monthly time series with imputation marks + inline anomaly
  // flags. Always rendered when present.
  series: SalesSeriesResponse | null
  // Prophet forecast payload. When provided AND non-null, the chart layers
  // the prediction line + confidence band on top of the historical bars and
  // draws a "today" reference line at the boundary.
  forecast: ForecastResult | null
  displayName?: string
}

interface Row {
  month: string         // YYYY-MM (used for sorting + ReferenceDot lookup)
  monthLabel: string    // "Mar '26" (visible on the X axis)
  // Historical bars (mutually exclusive — exactly one of these is set per
  // historical row so Recharts can colour them differently)
  observed: number | null
  imputed: number | null
  imputeMethod: string | null
  // Forecast layer
  yhat: number | null
  bandBase: number | null
  bandHeight: number | null
  // 3-month rolling avg over observed + imputed (NaN-aware)
  avg: number | null
  // Anomaly z-score, or null
  anomalyZ: number | null
}

function rollingAvg(values: (number | null)[], window = 3): (number | null)[] {
  return values.map((_, i) => {
    if (i < window - 1) return null
    const slice = values.slice(i - window + 1, i + 1)
    if (slice.some(v => v == null)) return null
    return Math.round(slice.reduce<number>((s, v) => s + (v as number), 0) / window)
  })
}

function buildRows(series: SalesSeriesResponse | null, forecast: ForecastResult | null): Row[] {
  const rows: Row[] = []
  const histVals: (number | null)[] = []

  if (series) {
    for (const h of series.history) {
      const v = h.units
      histVals.push(v)
      rows.push({
        month: h.month,
        monthLabel: formatMonth(h.month),
        observed: h.imputed ? null : v,
        imputed: h.imputed ? v : null,
        imputeMethod: h.impute_method,
        yhat: null,
        bandBase: null,
        bandHeight: null,
        avg: null, // filled below
        anomalyZ: h.anomaly?.z_score ?? null,
      })
    }
  }

  // Compute rolling avg over the historical values, then assign back.
  const avgValues = rollingAvg(histVals)
  for (let i = 0; i < rows.length; i++) {
    rows[i].avg = avgValues[i]
  }

  if (forecast) {
    for (const f of forecast.forecast) {
      // Use stacked Area: bandBase = lower, bandHeight = upper - lower
      const base = f.yhat_lower
      const height = Math.max(0, f.yhat_upper - f.yhat_lower)
      rows.push({
        month: f.month,
        monthLabel: formatMonth(f.month),
        observed: null,
        imputed: null,
        imputeMethod: null,
        yhat: f.yhat,
        bandBase: base,
        bandHeight: height,
        avg: null,
        anomalyZ: null,
      })
    }
  }

  return rows
}

function findTodayLabel(rows: Row[]): string | null {
  // The boundary is the last historical row (any with observed OR imputed set).
  for (let i = rows.length - 1; i >= 0; i--) {
    if (rows[i].observed != null || rows[i].imputed != null) {
      return rows[i].monthLabel
    }
  }
  return null
}

export function SalesChart({ series, forecast, displayName }: Props) {
  if (!series || series.history.length === 0) {
    return (
      <Card className="h-64 flex items-center justify-center">
        <p className="text-muted-foreground">
          No data yet — click Refresh Data to fetch sales figures.
        </p>
      </Card>
    )
  }

  const rows = buildRows(series, forecast)
  const todayLabel = forecast ? findTodayLabel(rows) : null
  const intervalPct = forecast ? Math.round(forecast.interval_width * 100) : 95

  return (
    <Card>
      <CardContent>
        <h3 className="text-lg font-semibold mb-2">
          Monthly Sales — {displayName ?? 'Selected bike'} (India)
        </h3>
        <ResponsiveContainer width="100%" height={320}>
          <ComposedChart data={rows} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis dataKey="monthLabel" tick={{ fill: '#94a3b8', fontSize: 12 }} />
            <YAxis
              tickFormatter={v => `${(v / 1000).toFixed(0)}k`}
              tick={{ fill: '#94a3b8', fontSize: 12 }}
            />
            <Tooltip
              contentStyle={{ background: '#1e293b', border: '1px solid #475569', borderRadius: 8 }}
              labelStyle={{ color: '#e2e8f0' }}
              formatter={(value, name) => {
                if (value == null) return ['—', name]
                const num = typeof value === 'number' ? Math.round(value).toLocaleString() : value
                const labels: Record<string, string> = {
                  observed: 'Observed',
                  imputed: 'Imputed',
                  avg: '3-mo rolling avg',
                  yhat: 'Forecast',
                  bandBase: `${intervalPct}% CI lower`,
                  bandHeight: 'CI height',
                }
                return [num, labels[String(name)] ?? name]
              }}
            />
            <Legend
              wrapperStyle={{ color: '#94a3b8', fontSize: 12 }}
              formatter={v => {
                const m: Record<string, string> = {
                  observed: 'Observed',
                  imputed: 'Imputed',
                  avg: '3-mo Rolling Avg',
                  yhat: 'Forecast',
                  bandHeight: `${intervalPct}% CI`,
                }
                return m[v as string] ?? v
              }}
            />

            {/* Confidence band — invisible base + coloured top so it renders
                as a band only across the forecast horizon. */}
            {forecast && (
              <Area
                type="monotone"
                dataKey="bandBase"
                stackId="ci"
                stroke="none"
                fill="transparent"
                isAnimationActive={false}
                legendType="none"
              />
            )}
            {forecast && (
              <Area
                type="monotone"
                dataKey="bandHeight"
                stackId="ci"
                stroke="none"
                fill="#a78bfa"
                fillOpacity={0.18}
                isAnimationActive={false}
                legendType="none"
              />
            )}

            {/* Historical bars — solid for observed, lighter + dashed-stroke
                for imputed. Same colour so the eye reads them as one series. */}
            <Bar
              dataKey="observed"
              fill="#3b82f6"
              radius={[4, 4, 0, 0]}
              isAnimationActive={false}
              legendType="none"
            />
            <Bar
              dataKey="imputed"
              fill="#3b82f6"
              fillOpacity={0.4}
              stroke="#60a5fa"
              strokeDasharray="3 3"
              radius={[4, 4, 0, 0]}
              isAnimationActive={false}
              legendType="none"
            />

            {/* 3-month rolling avg — orange line over historical points */}
            <Line
              type="monotone"
              dataKey="avg"
              stroke="#f59e0b"
              strokeWidth={2}
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
              legendType="none"
            />

            {/* Forecast line (only on rows that have yhat) */}
            {forecast && (
              <Line
                type="monotone"
                dataKey="yhat"
                stroke="#a78bfa"
                strokeWidth={2}
                dot={{ fill: '#a78bfa', r: 3 }}
                connectNulls={false}
                isAnimationActive={false}
                legendType="none"
              />
            )}

            {/* Vertical "today" boundary between history and forecast */}
            {todayLabel && (
              <ReferenceLine
                x={todayLabel}
                stroke="#64748b"
                strokeDasharray="4 4"
                label={{
                  value: 'today',
                  fill: '#94a3b8',
                  fontSize: 11,
                  position: 'insideTopRight',
                }}
              />
            )}

            {/* Anomaly markers — always shown (historical truth, not gated
                on the forecast toggle). */}
            {series.anomalies.map(a => (
              <ReferenceDot
                key={a.month}
                x={formatMonth(a.month)}
                y={a.units}
                r={6}
                fill="#f59e0b"
                stroke="#1e293b"
                strokeWidth={2}
              />
            ))}
          </ComposedChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}
