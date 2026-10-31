import type { PoolScope } from '../../api/themesApi'

export function ReviewPoolPicker({
  isBrandMode,
  poolScope,
  onChange,
}: {
  isBrandMode: boolean
  poolScope: PoolScope
  onChange: (scope: PoolScope) => void
}) {
  return (
    <>
      {!isBrandMode && (
        <div>
          <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
            Review Pool
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {([
              {
                id: 'bike' as PoolScope,
                label: 'Just this bike',
                detail: 'Cluster only the selected bike\'s reviews. Best for popular bikes with plenty of feedback.',
              },
              {
                id: 'brand' as PoolScope,
                label: 'Brand-wide pool',
                detail: 'Cluster all reviews of every bike from this brand. Niche bikes inherit themes from siblings; each theme shows a "share of this bike" badge.',
              },
            ]).map(opt => (
              <button
                key={opt.id}
                type="button"
                onClick={() => onChange(opt.id)}
                className={`text-left rounded-xl border px-4 py-3 transition-colors ${
                  poolScope === opt.id
                    ? 'border-primary bg-primary/10'
                    : 'border-border bg-card hover:bg-accent'
                }`}
              >
                <div className="font-medium text-sm">{opt.label}</div>
                <div className="text-xs text-muted-foreground mt-1 leading-relaxed">
                  {opt.detail}
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {isBrandMode && (
        <div className="text-xs text-muted-foreground border-l-2 border-primary/40 pl-3 leading-relaxed">
          You're in <strong className="text-foreground">All models</strong> mode — themes are clustered across every bike in the brand. Pick a specific model from the dropdown to localize and see "% this bike" badges per theme.
        </div>
      )}
    </>
  )
}
