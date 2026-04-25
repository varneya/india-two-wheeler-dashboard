import { Star, StarOff } from 'lucide-react'
import { useState } from 'react'
import type { Review } from '../types/reviews'
import { Badge } from './ui/badge'
import { Button } from './ui/button'
import { Card, CardContent } from './ui/card'

interface Props {
  review: Review
}

function Stars({ rating }: { rating: number }) {
  const filled = Math.round(rating)
  return (
    <span className="flex items-center gap-1 text-amber-400">
      {Array.from({ length: 5 }).map((_, i) =>
        i < filled
          ? <Star key={i} className="size-3.5 fill-amber-400" />
          : <StarOff key={i} className="size-3.5 text-muted-foreground/40" />,
      )}
      <span className="text-muted-foreground text-xs ml-1">{rating.toFixed(1)}/5</span>
    </span>
  )
}

export function ReviewCard({ review }: Props) {
  const [expanded, setExpanded] = useState(false)
  const isTeamBhp = review.source === 'team-bhp'
  const previewLen = 300
  const long = review.review_text.length > previewLen
  const displayText = expanded || !long
    ? review.review_text
    : review.review_text.slice(0, previewLen) + '…'

  return (
    <Card className="py-4 gap-2">
      <CardContent className="flex flex-col gap-2">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-2">
            <Badge variant={isTeamBhp ? 'info' : 'warning'}>
              {isTeamBhp ? 'Team-BHP' : 'BikeWale'}
            </Badge>
            {review.username && (
              <span className="text-foreground text-sm font-medium">{review.username}</span>
            )}
          </div>
          <div className="flex items-center gap-3">
            {review.overall_rating != null && <Stars rating={review.overall_rating} />}
            {review.thread_url && (
              <a
                href={review.thread_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Source ↗
              </a>
            )}
          </div>
        </div>

        <p className="text-muted-foreground text-sm leading-relaxed whitespace-pre-line">{displayText}</p>

        {long && (
          <Button
            variant="link"
            size="sm"
            className="h-auto p-0 text-xs self-start"
            onClick={() => setExpanded(e => !e)}
          >
            {expanded ? 'Show less' : 'Read more'}
          </Button>
        )}
      </CardContent>
    </Card>
  )
}
