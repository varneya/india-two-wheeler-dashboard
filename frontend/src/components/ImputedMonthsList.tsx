import type { SeriesHistoryPoint } from '../types/sales'
import { formatMonth } from '../utils/format'
import { Badge } from './ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from './ui/card'

const METHOD_LABEL: Record<string, string> = {
  seasonal_naive: 'seasonal-naive',
  linear: 'linear',
  ffill: 'forward-fill',
  median: 'median window',
}

function MethodBadge({ method }: { method: string | null }) {
  if (!method) return null
  return (
    <Badge variant="warning" className="rounded-full">
      imputed · {METHOD_LABEL[method] ?? method}
    </Badge>
  )
}

/**
 * One row per imputed month with its filled value + the method that filled
 * it. Renders nothing when the history is fully observed so the parent can
 * lay it out in a conditional 2-column strip without empty boxes.
 */
export function ImputedMonthsList({ history }: { history: SeriesHistoryPoint[] }) {
  const imputed = history.filter(h => h.imputed)
  if (imputed.length === 0) return null
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          Imputed months ({imputed.length})
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        {imputed.map(h => (
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
  )
}
