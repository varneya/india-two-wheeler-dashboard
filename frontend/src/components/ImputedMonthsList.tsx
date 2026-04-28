import type { SeriesHistoryPoint } from '../types/sales'
import { formatMonth } from '../utils/format'
import { Badge } from './ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from './ui/card'

// Plain-English versions of the imputation method labels — the underlying
// methods are still seasonal-naive, linear, etc., but the UI now describes
// what they DID rather than the algorithm name.
const METHOD_LABEL: Record<string, string> = {
  seasonal_naive: 'matched same month last year',
  linear: 'between surrounding months',
  ffill: 'carried forward',
  median: 'median of nearby months',
}

function MethodBadge({ method }: { method: string | null }) {
  if (!method) return null
  return (
    <Badge variant="secondary" className="rounded-full text-xs">
      {METHOD_LABEL[method] ?? method}
    </Badge>
  )
}

/**
 * One row per estimated month with the value we filled in and a friendly
 * label for HOW we estimated it. Renders nothing when the history is fully
 * observed so the parent can lay it out in a conditional 2-column strip.
 */
export function ImputedMonthsList({ history }: { history: SeriesHistoryPoint[] }) {
  const imputed = history.filter(h => h.imputed)
  if (imputed.length === 0) return null
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          Estimated months ({imputed.length})
        </CardTitle>
        <p className="text-xs text-muted-foreground mt-1">
          Months where no source reported a number — we filled them in based
          on surrounding data so trends stay smooth.
        </p>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        {imputed.map(h => (
          <div key={h.month} className="flex items-center gap-3 flex-wrap">
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
  )
}
