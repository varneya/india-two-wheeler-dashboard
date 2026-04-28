import { useState } from 'react'
import { SOURCE_META, type SalesDataPoint } from '../types/sales'
import { formatMonth } from '../utils/format'
import { Badge } from './ui/badge'
import { Card, CardHeader, CardTitle } from './ui/card'

interface Props {
  sales: SalesDataPoint[]
}

type SortKey = 'month' | 'units_sold'

// Returns the MoM delta percentage, or null when the prior-month value is too
// small to be a meaningful denominator (in which case the calc would produce
// noisy "+53000%" outputs that look like broken data).
function momDelta(current: number, prev: number | undefined): number | null {
  if (prev === undefined) return null
  if (prev <= 500) return null
  const pct = ((current - prev) / prev) * 100
  return Math.max(-999, Math.min(999, pct))
}

export function SalesTable({ sales }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>('month')
  const [sortAsc, setSortAsc] = useState(false)

  function toggleSort(key: SortKey) {
    if (sortKey === key) setSortAsc(a => !a)
    else { setSortKey(key); setSortAsc(false) }
  }

  const sorted = [...sales].sort((a, b) => {
    const cmp = sortKey === 'month'
      ? a.month.localeCompare(b.month)
      : a.units_sold - b.units_sold
    return sortAsc ? cmp : -cmp
  })

  const salesByMonth = Object.fromEntries(sales.map(s => [s.month, s.units_sold]))

  function prevUnits(month: string): number | undefined {
    const allMonths = sales.map(s => s.month).sort()
    const idx = allMonths.indexOf(month)
    if (idx <= 0) return undefined
    return salesByMonth[allMonths[idx - 1]]
  }

  function SortIcon({ k }: { k: SortKey }) {
    if (sortKey !== k) return <span className="text-slate-600 ml-1">↕</span>
    return <span className="text-blue-400 ml-1">{sortAsc ? '↑' : '↓'}</span>
  }

  return (
    <Card className="overflow-hidden gap-0 py-0">
      <CardHeader className="pt-5 pb-3">
        <CardTitle className="text-lg">Historical Data</CardTitle>
      </CardHeader>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-muted-foreground uppercase text-xs tracking-wide">
              <th
                className="text-left px-5 py-3 cursor-pointer hover:text-white select-none"
                onClick={() => toggleSort('month')}
              >
                Month <SortIcon k="month" />
              </th>
              <th
                className="text-right px-5 py-3 cursor-pointer hover:text-white select-none"
                onClick={() => toggleSort('units_sold')}
              >
                Units Sold <SortIcon k="units_sold" />
              </th>
              <th className="text-right px-5 py-3">vs Prior Month</th>
              <th className="text-left px-5 py-3">Source</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map(row => {
              const prev = prevUnits(row.month)
              const delta = momDelta(row.units_sold, prev)
              return (
                <tr key={row.month} className="border-b border-border/50 hover:bg-accent/30 transition-colors">
                  <td className="px-5 py-3 text-foreground font-medium">{formatMonth(row.month)}</td>
                  <td className="px-5 py-3 text-right text-foreground font-mono">{row.units_sold.toLocaleString()}</td>
                  <td className="px-5 py-3 text-right font-mono">
                    {delta !== null ? (
                      <span className={delta >= 0 ? 'text-emerald-400' : 'text-red-400'}>
                        {delta >= 0 ? '+' : ''}{delta.toFixed(1)}%
                      </span>
                    ) : (
                      <span className="text-muted-foreground/60">—</span>
                    )}
                  </td>
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-2 min-w-0">
                      {row.source && (
                        <Badge
                          variant={
                            row.source === 'autopunditz' ? 'secondary'
                            : row.source === 'rushlane' ? 'info'
                            : 'outline'
                          }
                          className="text-[10px] px-1.5 py-0.5"
                        >
                          {SOURCE_META[row.source]?.label ?? row.source}
                        </Badge>
                      )}
                      {row.source_url ? (
                        <a
                          href={row.source_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-blue-400 hover:text-blue-300 truncate min-w-0"
                        >
                          {new URL(row.source_url).hostname.replace('www.', '')}
                        </a>
                      ) : (
                        <span className="text-muted-foreground/60">—</span>
                      )}
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {!sales.length && (
          <p className="text-muted-foreground text-center py-8">No data available.</p>
        )}
      </div>
    </Card>
  )
}
