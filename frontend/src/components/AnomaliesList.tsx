import { AlertTriangle } from 'lucide-react'
import type { AnomalyPoint } from '../api/salesApi'
import { formatMonth } from '../utils/format'
import { Badge } from './ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from './ui/card'

/**
 * Compact list of historically anomalous months. Same shape used by both the
 * Prophet payload's `anomalies` field and the cheaper /sales/series endpoint.
 * Renders nothing when there are no items so the parent can lay it out in a
 * conditional 2-column strip without empty boxes.
 */
export function AnomaliesList({ items }: { items: AnomalyPoint[] }) {
  if (items.length === 0) return null
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          <AlertTriangle className="size-4 text-amber-400" />
          Unusual months ({items.length})
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {items.map(a => {
          const direction = a.z_score >= 0 ? 'jump' : 'drop'
          const delta = Math.round(a.units - a.prev_units)
          const deltaStr = `${delta >= 0 ? '+' : ''}${delta.toLocaleString()}`
          return (
            <div key={a.month} className="text-sm flex items-start gap-3">
              <span className="font-mono text-xs text-muted-foreground w-16 shrink-0">
                {formatMonth(a.month)}
              </span>
              <div className="flex-1 min-w-0">
                <div>
                  <span className="font-medium">{Math.round(a.units).toLocaleString()}</span>{' '}
                  <span className="text-muted-foreground">
                    (prev {Math.round(a.prev_units).toLocaleString()}, {deltaStr})
                  </span>
                </div>
                <div className="text-xs text-muted-foreground">
                  Stands out from the surrounding months — worth a look.
                </div>
              </div>
              <Badge
                variant={Math.abs(a.z_score) >= 4 ? 'destructive' : 'warning'}
                className="rounded-full"
              >
                Unusual {direction}
              </Badge>
            </div>
          )
        })}
      </CardContent>
    </Card>
  )
}
