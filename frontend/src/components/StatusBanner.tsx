import type { Metrics } from '../types/sales'

interface Props {
  metrics: Metrics | null
}

export function StatusBanner({ metrics }: Props) {
  if (!metrics) return null

  const stale = (() => {
    if (!metrics.last_refresh) return true
    const diff = Date.now() - new Date(metrics.last_refresh).getTime()
    return diff > 30 * 24 * 60 * 60 * 1000
  })()

  const lastUpdated = metrics.last_refresh
    ? new Date(metrics.last_refresh).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })
    : 'Never'

  return (
    <div className={`rounded-lg px-4 py-2 text-sm flex items-center gap-2 ${stale ? 'bg-amber-900/40 border border-amber-700/50 text-amber-300' : 'bg-slate-800 border border-slate-700 text-slate-400'}`}>
      {stale && <span>⚠</span>}
      <span>Last updated: {lastUpdated}</span>
      <span className="text-slate-600">·</span>
      <span>{metrics.months_tracked} month{metrics.months_tracked !== 1 ? 's' : ''} tracked</span>
    </div>
  )
}
