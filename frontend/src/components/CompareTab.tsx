import { useQuery } from '@tanstack/react-query'
import { X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { fetchBikes, fetchCompare } from '../api/bikesApi'
import { Button } from './ui/button'
import { Card, CardContent } from './ui/card'

const COLORS = ['#60a5fa', '#fbbf24', '#34d399', '#f87171']

function formatUnits(n: number) {
  if (n >= 100_000) return `${(n / 100_000).toFixed(1)}L`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  return String(n)
}

function formatMonth(m: string) {
  const [y, mo] = m.split('-')
  const idx = parseInt(mo, 10) - 1
  const names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
  return `${names[idx]} '${y.slice(-2)}`
}

interface Props {
  // When the Compare section is embedded under a specific bike's chart,
  // anchor that bike as the first selection so the user only has to add
  // 1+ comparators rather than re-pick the bike they're already viewing.
  anchorBikeId?: string | null
}

export function CompareTab({ anchorBikeId = null }: Props = {}) {
  const [selected, setSelected] = useState<string[]>(
    anchorBikeId ? [anchorBikeId] : [],
  )
  const [filter, setFilter] = useState('')
  const [brandFilter, setBrandFilter] = useState<string | null>(null)

  // When the user navigates to a different anchor bike (selectedBikeId
  // changes), reset the selection so it re-seeds with the new anchor.
  // Skipped when `selected` already differs intentionally — we only reset
  // when the previous selection looks like the prior anchor alone.
  useEffect(() => {
    if (!anchorBikeId) return
    setSelected(prev =>
      prev.length === 0 || (prev.length === 1 && prev[0] !== anchorBikeId)
        ? [anchorBikeId]
        : prev,
    )
  }, [anchorBikeId])

  const { data: bikes = [] } = useQuery({ queryKey: ['bikes'], queryFn: fetchBikes })

  const eligible = useMemo(
    () => bikes.filter(b => b.months_tracked > 0),
    [bikes],
  )

  // Distinct brands present in the eligible-bikes list, with counts
  const brandsWithCounts = useMemo(() => {
    const m = new Map<string, number>()
    for (const b of eligible) m.set(b.brand, (m.get(b.brand) ?? 0) + 1)
    return Array.from(m.entries()).sort((a, b) => b[1] - a[1])
  }, [eligible])

  const filteredBikes = useMemo(() => {
    const q = filter.toLowerCase().trim()
    return eligible.filter(b => {
      if (brandFilter && b.brand !== brandFilter) return false
      if (!q) return true
      return (
        b.display_name.toLowerCase().includes(q) ||
        b.brand.toLowerCase().includes(q)
      )
    })
  }, [eligible, filter, brandFilter])

  function toggle(id: string) {
    setSelected(prev => {
      if (prev.includes(id)) return prev.filter(p => p !== id)
      if (prev.length >= 4) return prev
      return [...prev, id]
    })
  }

  const compareQ = useQuery({
    queryKey: ['compare', selected.join(',')],
    queryFn: () => fetchCompare(selected),
    enabled: selected.length >= 2,
  })

  const chartData = useMemo(() => {
    if (!compareQ.data) return []
    const monthSet = new Set<string>()
    compareQ.data.series.forEach(s => monthSet.add(s.month))
    const months = Array.from(monthSet).sort()
    return months.map(month => {
      const row: Record<string, string | number> = { month, monthLabel: formatMonth(month) }
      for (const b of compareQ.data!.bikes) {
        const point = compareQ.data!.series.find(s => s.month === month && s.bike_id === b.id)
        row[b.id] = point?.units_sold ?? 0
      }
      return row
    })
  }, [compareQ.data])

  return (
    <div className="space-y-6">

      {/* Bike picker chips */}
      <Card>
        <CardContent className="space-y-3">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
            Select 2–4 bikes to compare
          </p>
          <span className="text-xs text-muted-foreground/70">
            {selected.length}/4 selected
          </span>
        </div>

        {/* Selected pills */}
        {selected.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {selected.map((id, i) => {
              const b = bikes.find(x => x.id === id)
              return (
                <Button
                  key={id}
                  variant="secondary"
                  size="sm"
                  onClick={() => toggle(id)}
                  className="rounded-full h-7 px-2.5 gap-1.5"
                  style={{ borderLeft: `3px solid ${COLORS[i]}` }}
                >
                  <span>{b?.display_name ?? id}</span>
                  <X className="size-3 opacity-60" />
                </Button>
              )
            })}
          </div>
        )}

        {/* Brand filter chips */}
        <div className="flex flex-wrap gap-1.5">
          <Button
            size="sm"
            variant={brandFilter === null ? 'default' : 'secondary'}
            onClick={() => setBrandFilter(null)}
            className="rounded-full h-7 px-2.5"
          >
            All brands
          </Button>
          {brandsWithCounts.map(([brand, count]) => (
            <Button
              key={brand}
              size="sm"
              variant={brandFilter === brand ? 'default' : 'secondary'}
              onClick={() => setBrandFilter(brand === brandFilter ? null : brand)}
              className="rounded-full h-7 px-2.5"
            >
              {brand} <span className="opacity-60 ml-1">{count}</span>
            </Button>
          ))}
        </div>

        {/* Search */}
        <input
          type="text"
          placeholder="Search bikes…"
          value={filter}
          onChange={e => setFilter(e.target.value)}
          className="w-full bg-background text-foreground placeholder-muted-foreground rounded-md px-3 py-2 text-sm outline-none border border-input focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px]"
        />

        {/* Bike grid */}
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-1.5 max-h-56 overflow-y-auto">
          {filteredBikes.map(b => {
            const checked = selected.includes(b.id)
            const disabled = !checked && selected.length >= 4
            return (
              <button
                key={b.id}
                disabled={disabled}
                onClick={() => toggle(b.id)}
                className={`text-left px-2.5 py-1.5 rounded-lg text-xs transition-colors border ${
                  checked
                    ? 'bg-primary/15 border-primary/60 text-foreground'
                    : disabled
                    ? 'bg-card/50 border-border text-muted-foreground/60 cursor-not-allowed'
                    : 'bg-card border-border hover:border-input/60 text-muted-foreground hover:text-foreground'
                }`}
              >
                <p className="truncate font-medium">{b.display_name}</p>
                <p className="text-[10px] opacity-70">
                  {formatUnits(b.total_units)} · {b.months_tracked}m
                </p>
              </button>
            )
          })}
        </div>
        </CardContent>
      </Card>

      {/* Empty state. Tailor the copy when an anchor bike is pre-selected
          so the user knows they only need to pick 1 more, not 2 from
          scratch. */}
      {selected.length < 2 && (() => {
        const anchorName = anchorBikeId
          ? (bikes.find(b => b.id === anchorBikeId)?.display_name ?? null)
          : null
        return (
          <Card className="p-12 text-center">
            <p className="text-muted-foreground">
              {anchorName
                ? <>Pick another bike above to compare with <strong className="text-foreground">{anchorName}</strong>.</>
                : 'Pick at least 2 bikes above to overlay their monthly sales.'}
            </p>
          </Card>
        )
      })()}

      {/* Chart + table */}
      {selected.length >= 2 && compareQ.data && (
        <>
          <Card>
            <CardContent>
              <h3 className="text-sm font-medium text-foreground mb-3">Monthly Sales Comparison</h3>
            <ResponsiveContainer width="100%" height={360}>
              <LineChart data={chartData} margin={{ top: 8, right: 12, bottom: 4, left: -8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis dataKey="monthLabel" tick={{ fill: '#94a3b8', fontSize: 12 }} />
                <YAxis
                  tickFormatter={v => `${(v / 1000).toFixed(0)}k`}
                  tick={{ fill: '#94a3b8', fontSize: 12 }}
                />
                <Tooltip
                  contentStyle={{ background: '#1e293b', border: '1px solid #475569', borderRadius: 8 }}
                  labelStyle={{ color: '#e2e8f0' }}
                  formatter={(v) =>
                    typeof v === 'number' ? v.toLocaleString() : v
                  }
                />
                <Legend wrapperStyle={{ color: '#94a3b8', fontSize: 12 }} />
                {compareQ.data.bikes.map((b, i) => (
                  <Line
                    key={b.id}
                    type="monotone"
                    dataKey={b.id}
                    name={b.display_name}
                    stroke={COLORS[i]}
                    strokeWidth={2}
                    dot={{ r: 3 }}
                    activeDot={{ r: 5 }}
                    connectNulls
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
            </CardContent>
          </Card>

          {/* Comparison table */}
          <Card className="overflow-hidden gap-0 py-0">
            <table className="w-full text-sm">
              <thead className="bg-secondary/50 text-foreground">
                <tr>
                  <th className="text-left px-4 py-3 font-medium">Bike</th>
                  <th className="text-right px-4 py-3 font-medium">Total units</th>
                  <th className="text-right px-4 py-3 font-medium">Avg / month</th>
                  <th className="text-left px-4 py-3 font-medium">Peak month</th>
                  <th className="text-right px-4 py-3 font-medium">Peak units</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {compareQ.data.bikes.map((b, i) => (
                  <tr key={b.id} className="text-foreground">
                    <td className="px-4 py-2.5 flex items-center gap-2">
                      <span
                        className="w-2.5 h-2.5 rounded-full"
                        style={{ background: COLORS[i] }}
                      />
                      <span>{b.display_name}</span>
                    </td>
                    <td className="text-right tabular-nums px-4 py-2.5">
                      {b.total_units.toLocaleString()}
                    </td>
                    <td className="text-right tabular-nums px-4 py-2.5">
                      {b.avg_per_month.toLocaleString()}
                    </td>
                    <td className="px-4 py-2.5 text-muted-foreground">
                      {b.peak_month ? formatMonth(b.peak_month) : '—'}
                    </td>
                    <td className="text-right tabular-nums px-4 py-2.5">
                      {b.peak_units.toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </>
      )}
    </div>
  )
}
