import { useEffect, useRef, useState } from 'react'
import {
  Area,
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  ReferenceDot,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { AlertTriangle, Loader2, RefreshCw } from 'lucide-react'

import {
  fetchForecast,
  fetchForecastStatus,
  triggerForecastRefresh,
  type AnomalyPoint,
  type ForecastResult,
} from '../api/salesApi'
import { useSelectedBike } from '../context/SelectedBike'
import { formatMonth } from '../utils/format'
import { Badge } from './ui/badge'
import { Button } from './ui/button'
import { Card, CardContent, CardHeader, CardTitle } from './ui/card'

type Row = {
  month: string
  monthLabel: string
  // Historical
  observed: number | null
  imputed: number | null
  imputeMethod: string | null
  // Forecast
  yhat: number | null
  band: [number, number] | null
}

function buildRows(result: ForecastResult): Row[] {
  const rows: Row[] = []
  for (const h of result.history) {
    rows.push({
      month: h.month,
      monthLabel: formatMonth(h.month),
      observed: h.imputed ? null : h.units,
      imputed: h.imputed ? h.units : null,
      imputeMethod: h.impute_method,
      yhat: null,
      band: null,
    })
  }
  for (const f of result.forecast) {
    rows.push({
      month: f.month,
      monthLabel: formatMonth(f.month),
      observed: null,
      imputed: null,
      imputeMethod: null,
      yhat: f.yhat,
      band: [f.yhat_lower, f.yhat_upper - f.yhat_lower],   // base + height for stacked area
    })
  }
  return rows
}

function MethodBadge({ method }: { method: string | null }) {
  if (!method) return null
  const labels: Record<string, string> = {
    seasonal_naive: 'seasonal-naive',
    linear: 'linear',
    ffill: 'forward-fill',
    median: 'median window',
  }
  return (
    <Badge variant="warning" className="rounded-full">
      imputed · {labels[method] ?? method}
    </Badge>
  )
}

function AnomaliesList({ items }: { items: AnomalyPoint[] }) {
  if (items.length === 0) return null
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          <AlertTriangle className="size-4 text-amber-400" />
          Anomalies detected ({items.length})
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {items.map(a => (
          <div key={a.month} className="text-sm flex items-start gap-3">
            <span className="font-mono text-xs text-muted-foreground w-16 shrink-0">
              {formatMonth(a.month)}
            </span>
            <div className="flex-1 min-w-0">
              <div>
                <span className="font-medium">{Math.round(a.units).toLocaleString()}</span>{' '}
                <span className="text-muted-foreground">
                  (prev {Math.round(a.prev_units).toLocaleString()})
                </span>
              </div>
              <div className="text-xs text-muted-foreground">{a.reason}</div>
            </div>
            <Badge
              variant={Math.abs(a.z_score) >= 4 ? 'destructive' : 'warning'}
              className="rounded-full font-mono"
            >
              z={a.z_score >= 0 ? '+' : ''}{a.z_score.toFixed(1)}σ
            </Badge>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

export function ForecastTab() {
  const { selectedBikeId } = useSelectedBike()
  const [result, setResult] = useState<ForecastResult | null>(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [horizon, setHorizon] = useState(6)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  function stopPolling() {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  async function load(force: boolean) {
    if (!selectedBikeId) return
    setError(null)
    if (force) {
      setPending(true)
      try {
        await triggerForecastRefresh(selectedBikeId, { horizon })
      } catch (e) {
        setError(String(e))
        setPending(false)
        return
      }
    }
    try {
      const r = await fetchForecast(selectedBikeId, { horizon })
      if ('pending' in r) {
        setPending(true)
        // Poll status
        pollRef.current = setInterval(async () => {
          try {
            const st = await fetchForecastStatus(selectedBikeId)
            if (st.stage === 'done') {
              stopPolling()
              const fresh = await fetchForecast(selectedBikeId, { horizon })
              if (!('pending' in fresh)) {
                setResult(fresh)
                setPending(false)
              }
            } else if (st.stage === 'error') {
              stopPolling()
              setError(st.error || 'forecast fit failed')
              setPending(false)
            }
          } catch (e) {
            stopPolling()
            setError(String(e))
            setPending(false)
          }
        }, 2000)
      } else {
        setResult(r)
        setPending(false)
      }
    } catch (e) {
      setError(String(e))
      setPending(false)
    }
  }

  useEffect(() => {
    setResult(null)
    setError(null)
    setPending(false)
    stopPolling()
    void load(false)
    return stopPolling
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedBikeId, horizon])

  if (!selectedBikeId) {
    return (
      <Card className="p-12 text-center">
        <p className="text-muted-foreground">Pick a bike from the dropdown to see its forecast.</p>
      </Card>
    )
  }

  const rows = result ? buildRows(result) : []
  const importedCount = result?.history.filter(h => h.imputed).length ?? 0

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-3 flex-wrap">
            <div>
              <CardTitle className="text-lg">Sales forecast (Prophet)</CardTitle>
              <p className="text-xs text-muted-foreground mt-1">
                Imputed missing months with priority{' '}
                <code>seasonal_naive → linear → ffill → median</code>, then fits a Prophet model
                with yearly seasonality.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <select
                value={horizon}
                onChange={e => setHorizon(parseInt(e.target.value, 10))}
                className="bg-card border border-border rounded-md px-2 py-1 text-sm"
              >
                {[3, 6, 9, 12, 18, 24].map(h => (
                  <option key={h} value={h}>{h} months</option>
                ))}
              </select>
              <Button
                size="sm"
                variant="outline"
                onClick={() => load(true)}
                disabled={pending}
              >
                {pending ? <Loader2 className="animate-spin size-3" /> : <RefreshCw className="size-3" />}
                Re-fit
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {/* Status pills */}
          <div className="flex flex-wrap gap-2 mb-4 text-xs">
            {result && (
              <>
                <Badge variant="secondary" className="rounded-full">
                  {result.n_observed} observed months
                </Badge>
                {importedCount > 0 && (
                  <Badge variant="warning" className="rounded-full">
                    {importedCount} imputed
                  </Badge>
                )}
                <Badge variant="info" className="rounded-full">
                  {result.horizon}-mo horizon · {(result.interval_width * 100).toFixed(0)}% CI
                </Badge>
                {result.low_confidence && (
                  <Badge variant="destructive" className="rounded-full">
                    low confidence — &lt; 12 mo of history
                  </Badge>
                )}
              </>
            )}
            {pending && (
              <Badge variant="info" className="rounded-full">
                <Loader2 className="size-3 animate-spin" /> fitting Prophet…
              </Badge>
            )}
          </div>

          {error && (
            <div className="bg-destructive/10 border border-destructive/40 text-destructive rounded-xl px-4 py-3 text-sm mb-4">
              {error}
            </div>
          )}

          {!result && !error && (
            <div className="h-64 flex items-center justify-center text-muted-foreground text-sm">
              {pending ? 'Fitting Prophet model — first run can take 5-30s…' : 'Loading…'}
            </div>
          )}

          {result && (
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
                      yhat: 'Forecast',
                      band: 'Confidence band',
                    }
                    return [num, labels[String(name)] ?? name]
                  }}
                />
                <Legend
                  formatter={v => {
                    const m: Record<string, string> = {
                      observed: 'Observed',
                      imputed: 'Imputed',
                      yhat: 'Forecast',
                      band: `${result ? (result.interval_width * 100).toFixed(0) : '95'}% CI`,
                    }
                    return m[v as string] ?? v
                  }}
                  wrapperStyle={{ color: '#94a3b8', fontSize: 12 }}
                />
                {/* Confidence band — invisible base + colored top so it renders as a band */}
                <Area
                  type="monotone"
                  dataKey={(r: Row) => (r.band ? r.band[0] : null)}
                  stackId="ci"
                  stroke="none"
                  fill="transparent"
                  isAnimationActive={false}
                  name="band-base"
                  legendType="none"
                />
                <Area
                  type="monotone"
                  dataKey={(r: Row) => (r.band ? r.band[1] : null)}
                  stackId="ci"
                  stroke="none"
                  fill="#a78bfa"
                  fillOpacity={0.18}
                  name="band"
                  isAnimationActive={false}
                />
                <Bar dataKey="observed" fill="#3b82f6" radius={[4, 4, 0, 0]} isAnimationActive={false} />
                <Bar dataKey="imputed" fill="#3b82f6" fillOpacity={0.45} radius={[4, 4, 0, 0]} isAnimationActive={false}>
                  {rows.map((_, i) => (
                    <Cell key={i} stroke="#60a5fa" strokeDasharray="3 3" />
                  ))}
                </Bar>
                <Line
                  type="monotone"
                  dataKey="yhat"
                  stroke="#a78bfa"
                  strokeWidth={2}
                  dot={{ fill: '#a78bfa', r: 3 }}
                  connectNulls={false}
                  isAnimationActive={false}
                />
                {result.anomalies.map(a => (
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
          )}
        </CardContent>
      </Card>

      {/* Imputation legend */}
      {result && importedCount > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Imputed months</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {result.history
              .filter(h => h.imputed)
              .map(h => (
                <div key={h.month} className="flex items-center gap-3">
                  <span className="font-mono text-xs text-muted-foreground w-16 shrink-0">
                    {formatMonth(h.month)}
                  </span>
                  <span className="font-medium">
                    {Math.round(h.units).toLocaleString()}
                  </span>
                  <MethodBadge method={h.impute_method} />
                </div>
              ))}
          </CardContent>
        </Card>
      )}

      {result && <AnomaliesList items={result.anomalies} />}
    </div>
  )
}
