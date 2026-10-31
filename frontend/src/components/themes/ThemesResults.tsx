import type { ThemesResult } from '../../types/themes'
import { Badge } from '../ui/badge'
import { ThemeCard } from './ThemeCard'

export function ThemesResults({ result }: { result: ThemesResult | null }) {
  if (!result?.themes?.length) return null

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
          Themes — {result.method}
          {result.run_at && (
            <span className="ml-2 font-normal normal-case text-slate-500">
              · {new Date(result.run_at).toLocaleString()}
            </span>
          )}
        </h2>
        <span className="text-xs text-slate-500">{result.themes.length} themes found</span>
      </div>

      {/* Sentiment summary bar */}
      <div className="flex gap-2 text-xs">
        {(['positive', 'negative', 'mixed'] as const).map(s => {
          const count = result.themes!.filter(t => t.sentiment === s).length
          if (!count) return null
          const colors: Record<string, string> = {
            positive: 'text-emerald-400',
            negative: 'text-red-400',
            mixed: 'text-amber-400',
          }
          return (
            <span key={s} className={`${colors[s]}`}>
              {count} {s}
            </span>
          )
        })}
      </div>

      {/* Quality metrics pills */}
      {result.metrics && (
        <div className="flex flex-wrap gap-2 text-xs">
          {result.metrics.npmi !== null && (
            <Badge
              variant={result.metrics.npmi >= 0.3 ? 'success' : result.metrics.npmi >= 0.1 ? 'info' : 'warning'}
              className="rounded-full"
              title="Normalised Pointwise Mutual Information — average pairwise coherence of theme keywords (>0.3 sharp, 0.1-0.3 decent, <0.1 noisy)"
            >
              coherence (NPMI) {result.metrics.npmi.toFixed(2)}
            </Badge>
          )}
          {result.metrics.theme_diversity !== null && (
            <Badge
              variant={result.metrics.theme_diversity >= 0.7 ? 'success' : 'info'}
              className="rounded-full"
              title="Fraction of unique tokens across all themes — high values mean themes don't overlap"
            >
              diversity {(result.metrics.theme_diversity * 100).toFixed(0)}%
            </Badge>
          )}
          <Badge variant="secondary" className="rounded-full" title="Reviews fed into the clustering">
            {result.metrics.n_reviews} reviews
          </Badge>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {result.themes.map((t, i) => (
          <ThemeCard key={t.name} theme={t} rank={i + 1} />
        ))}
      </div>
    </div>
  )
}
