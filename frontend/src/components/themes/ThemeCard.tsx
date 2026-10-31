import { useState } from 'react'
import type { Theme } from '../../types/themes'
import { Badge } from '../ui/badge'
import { Button } from '../ui/button'
import { Card, CardContent } from '../ui/card'

function SentimentBadge({ s }: { s: string }) {
  const variant: 'success' | 'destructive' | 'warning' =
    s === 'positive' ? 'success' : s === 'negative' ? 'destructive' : 'warning'
  return (
    <Badge variant={variant} className="rounded-full">
      {s}
    </Badge>
  )
}

export function ThemeCard({ theme, rank }: { theme: Theme; rank: number }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <Card className="py-4 gap-3">
      <CardContent className="space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2.5 min-w-0">
          <span className="text-xs font-bold text-muted-foreground/70 w-5 shrink-0">#{rank}</span>
          <p className="font-semibold text-foreground text-sm leading-tight">{theme.name}</p>
        </div>
        <div className="flex items-center gap-2 shrink-0 flex-wrap justify-end">
          {typeof theme.avg_rating === 'number' && (theme.rating_count ?? 0) > 0 && (
            <Badge
              variant={theme.avg_rating >= 4 ? 'success' : theme.avg_rating >= 3 ? 'info' : 'warning'}
              className="rounded-full"
              title={`Average rating across ${theme.rating_count} attributed reviews carrying a numeric rating`}
            >
              ★ {theme.avg_rating.toFixed(1)}
            </Badge>
          )}
          {typeof theme.localized_share === 'number' && (
            <Badge
              variant={theme.localized_share >= 0.4 ? 'success' : theme.localized_share >= 0.15 ? 'info' : 'secondary'}
              className="rounded-full"
              title="Fraction of this theme's reviews from the selected bike"
            >
              {Math.round(theme.localized_share * 100)}% this bike
            </Badge>
          )}
          <SentimentBadge s={theme.sentiment} />
          <span className="text-xs text-muted-foreground">{theme.mention_count} mentions</span>
        </div>
      </div>

      {/* Keywords */}
      <div className="flex flex-wrap gap-1.5">
        {theme.keywords.map(kw => (
          <Badge key={kw} variant="secondary" className="rounded-full">
            {kw}
          </Badge>
        ))}
      </div>

      {/* Quotes */}
      {theme.example_quotes.length > 0 && (
        <div className="space-y-1.5">
          {(expanded ? theme.example_quotes : theme.example_quotes.slice(0, 1)).map((q, i) => (
            <blockquote
              key={i}
              className="text-xs text-muted-foreground italic border-l-2 border-border pl-3 leading-relaxed"
            >
              "{q.length > 160 ? q.slice(0, 157) + '…' : q}"
            </blockquote>
          ))}
          {theme.example_quotes.length > 1 && (
            <Button
              variant="link"
              size="sm"
              className="h-auto p-0 text-xs"
              onClick={() => setExpanded(e => !e)}
            >
              {expanded ? 'Show less' : `+ ${theme.example_quotes.length - 1} more quote(s)`}
            </Button>
          )}
        </div>
      )}
      </CardContent>
    </Card>
  )
}
