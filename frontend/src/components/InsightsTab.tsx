import { ChevronDown, MessageSquare, Star } from 'lucide-react'
import { useState } from 'react'
import {
  ReviewList,
  ReviewRefreshButton,
  useReviewSummary,
} from './ReviewsTab'
import { ThemesTab } from './ThemesTab'
import { Badge } from './ui/badge'
import { Card, CardContent } from './ui/card'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from './ui/collapsible'

/**
 * Combined "Owner Insights" tab. Themes (AI-derived) are the primary view.
 * The raw owner reviews — which themes are derived from — live in a
 * Collapsible at the bottom for users who want to dig in.
 */
export function InsightsTab() {
  const [openReviews, setOpenReviews] = useState(false)
  const summaryQ = useReviewSummary()
  const summary = summaryQ.data

  const totalReviews = summary?.total ?? 0
  const avgRating = summary?.avg_rating

  return (
    <div className="flex flex-col gap-6">
      {/* Primary: Themes (whole existing ThemesTab content) */}
      <ThemesTab />

      {/* Secondary: collapsible raw reviews */}
      <Collapsible open={openReviews} onOpenChange={setOpenReviews}>
        <Card className="gap-0 py-0 overflow-hidden">
          <CollapsibleTrigger asChild>
            <button
              type="button"
              className="w-full flex items-center justify-between gap-3 px-5 py-4 text-left hover:bg-accent/30 transition-colors group"
            >
              <div className="flex items-center gap-3 min-w-0">
                <MessageSquare className="size-4 text-muted-foreground shrink-0" />
                <div className="flex flex-col gap-0.5 min-w-0">
                  <p className="text-sm font-medium text-foreground">
                    Raw owner reviews
                    {totalReviews > 0 && (
                      <span className="text-muted-foreground font-normal"> · {totalReviews}</span>
                    )}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    The reviews from which the themes above were derived.
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {avgRating != null && (
                  <Badge variant="secondary" className="gap-1">
                    <Star className="size-3 fill-amber-400 text-amber-400" />
                    {avgRating}/5
                  </Badge>
                )}
                <ChevronDown
                  className={`size-4 text-muted-foreground transition-transform ${
                    openReviews ? 'rotate-180' : ''
                  }`}
                />
              </div>
            </button>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <CardContent className="border-t border-border pt-5 pb-5 space-y-4">
              <div className="flex justify-end">
                <ReviewRefreshButton />
              </div>
              <ReviewList />
            </CardContent>
          </CollapsibleContent>
        </Card>
      </Collapsible>
    </div>
  )
}
