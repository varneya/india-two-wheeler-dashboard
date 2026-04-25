import { useQuery } from '@tanstack/react-query'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { fetchSourceComparison } from '../api/bikesApi'
import { formatMonth } from '../utils/format'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './ui/card'

interface Props {
  brandId: string | null
}

function formatThousands(n: number | null | undefined): string {
  if (n == null) return '—'
  const abs = Math.abs(n)
  if (abs >= 100_000) return `${(n / 100_000).toFixed(1)}L`
  if (abs >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  return String(n)
}

export function SourceComparisonCard({ brandId }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ['source-comparison', brandId],
    queryFn: () => fetchSourceComparison(brandId!),
    enabled: !!brandId,
  })

  if (!brandId) return null
  if (isLoading) {
    return <Card className="h-72 animate-pulse" />
  }
  if (!data) return null

  const hasOverlap = data.series.some(p => p.wholesale != null && p.retail != null)
  if (!hasOverlap) {
    const hasAnyRetail = data.series.some(p => p.retail != null)
    const reason = !hasAnyRetail
      ? `No FADA data for ${data.brand_display} yet. Click Data Refresh to fetch the latest monthly PDFs.`
      : `No overlapping months yet between RushLane and FADA data for ${data.brand_display}.`
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Sales by source · {data.brand_display}</CardTitle>
          <CardDescription>{reason}</CardDescription>
        </CardHeader>
      </Card>
    )
  }

  const trimmed = data.series.filter(p => p.wholesale != null || p.retail != null)
  const overlapPoints = trimmed.filter(
    p => p.wholesale != null && p.retail != null,
  )
  const avgAbsGap =
    overlapPoints.reduce((s, p) => s + Math.abs(p.source_gap ?? 0), 0) /
    Math.max(overlapPoints.length, 1)
  const latestWithBoth = [...overlapPoints].reverse()[0]

  const chartData = trimmed.map(p => ({
    month: formatMonth(p.month),
    wholesale: p.wholesale,
    retail: p.retail,
  }))

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div>
            <CardTitle className="text-lg">
              Sales by source · {data.brand_display}
            </CardTitle>
            <CardDescription className="mt-1 leading-relaxed text-xs">
              Brand-level. RushLane reports manufacturer-published monthly sales
              (typically dispatches; some brands' reports are Vahan-derived).
              FADA reports dealer registrations from Vahan. They can differ for
              many reasons — inventory timing, data-source differences, or
              reporting lag.
            </CardDescription>
          </div>
          {latestWithBoth && (
            <div className="text-right shrink-0">
              <p className="text-xs text-muted-foreground uppercase tracking-wider">
                {formatMonth(latestWithBoth.month)} gap
              </p>
              <p className="text-xl font-bold tabular-nums text-foreground">
                {formatThousands(Math.abs(latestWithBoth.source_gap ?? 0))}
              </p>
            </div>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">

      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={chartData} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
          <XAxis dataKey="month" tick={{ fill: '#94a3b8', fontSize: 12 }} />
          <YAxis
            tickFormatter={v => `${(v / 1000).toFixed(0)}k`}
            tick={{ fill: '#94a3b8', fontSize: 12 }}
          />
          <Tooltip
            contentStyle={{
              background: '#1e293b',
              border: '1px solid #475569',
              borderRadius: 8,
            }}
            labelStyle={{ color: '#e2e8f0' }}
            formatter={(value, name) => [
              typeof value === 'number' ? value.toLocaleString() : value,
              name === 'wholesale' ? 'RushLane' : 'FADA Retail',
            ]}
          />
          <Line
            type="monotone"
            dataKey="wholesale"
            name="wholesale"
            stroke="#3b82f6"
            strokeWidth={2}
            dot={{ r: 3 }}
            connectNulls={false}
          />
          <Line
            type="monotone"
            dataKey="retail"
            name="retail"
            stroke="#f59e0b"
            strokeWidth={2}
            dot={{ r: 3 }}
            connectNulls={false}
          />
        </LineChart>
      </ResponsiveContainer>

      <div className="flex items-center gap-5 text-xs">
        <span className="flex items-center gap-1.5 text-muted-foreground">
          <span className="w-3 h-0.5 bg-blue-500 rounded" /> RushLane
        </span>
        <span className="flex items-center gap-1.5 text-muted-foreground">
          <span className="w-3 h-0.5 bg-amber-500 rounded" /> FADA Retail
        </span>
        <span className="text-muted-foreground ml-auto">
          {overlapPoints.length} overlapping month{overlapPoints.length === 1 ? '' : 's'} · avg gap{' '}
          <span className="text-foreground">{formatThousands(Math.round(avgAbsGap))}</span>
        </span>
      </div>
      </CardContent>
    </Card>
  )
}
