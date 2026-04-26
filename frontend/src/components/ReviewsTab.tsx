import { useQueryClient } from '@tanstack/react-query'
import { Loader2, RefreshCw } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  fetchReviews,
  fetchReviewSummary,
  fetchReviewsRefreshStatus,
  triggerReviewsRefresh,
} from '../api/reviewsApi'
import { useSelectedBike } from '../context/SelectedBike'
import { ReviewCard } from './ReviewCard'
import { Button } from './ui/button'
import { Card, CardContent } from './ui/card'

// ---------------------------------------------------------------------------
// Refresh button (reusable)
// ---------------------------------------------------------------------------
export function ReviewRefreshButton() {
  const queryClient = useQueryClient()
  const { selectedBikeId } = useSelectedBike()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const baselineRef = useRef<string | null>(null)

  function stopPolling() {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }

  async function handleRefresh() {
    if (!selectedBikeId) return
    setLoading(true)
    setError(null)
    try {
      const status = await fetchReviewsRefreshStatus()
      baselineRef.current = status.run_at
      await triggerReviewsRefresh(selectedBikeId)

      pollRef.current = setInterval(async () => {
        try {
          const latest = await fetchReviewsRefreshStatus()
          if (latest.run_at !== baselineRef.current) {
            stopPolling()
            setLoading(false)
            queryClient.invalidateQueries({ queryKey: ['reviews', selectedBikeId] })
            queryClient.invalidateQueries({ queryKey: ['reviewSummary', selectedBikeId] })
          }
        } catch {
          stopPolling()
          setLoading(false)
        }
      }, 3000)
    } catch {
      setLoading(false)
      setError('Refresh failed — is the backend running?')
    }
  }

  useEffect(() => () => stopPolling(), [])

  return (
    <div className="flex items-center gap-3">
      <Button onClick={handleRefresh} disabled={loading} variant="secondary" size="sm">
        {loading ? <Loader2 className="animate-spin" /> : <RefreshCw />}
        {loading ? 'Scraping…' : 'Refresh Reviews'}
      </Button>
      {error && <p className="text-destructive text-sm">{error}</p>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Big summary cards (used only on the standalone Reviews tab if we ever
// reinstate it). The Insights tab uses CompactReviewSummary instead.
// ---------------------------------------------------------------------------
function SummaryCards({ summary }: { summary: any }) {
  const bw = summary.by_source?.['bikewale'] ?? 0
  const rated = summary.avg_rating != null
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
      <Card className="py-5 gap-1">
        <CardContent className="flex flex-col gap-1">
          <p className="text-muted-foreground text-xs font-medium uppercase tracking-wider">Total Reviews</p>
          <p className="text-3xl font-bold text-foreground">{summary.total}</p>
          <p className="text-muted-foreground text-sm">from BikeWale owners</p>
        </CardContent>
      </Card>
      <Card className="py-5 gap-1">
        <CardContent className="flex flex-col gap-1">
          <p className="text-muted-foreground text-xs font-medium uppercase tracking-wider">Average Rating</p>
          <p className="text-3xl font-bold text-foreground">{rated ? `${summary.avg_rating}/5` : '—'}</p>
          <p className="text-muted-foreground text-sm">{bw} user review{bw !== 1 ? 's' : ''} · BikeWale</p>
        </CardContent>
      </Card>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Compact summary for embedding inside another tab — single line
// ---------------------------------------------------------------------------
export function useReviewSummary() {
  const { selectedBikeId } = useSelectedBike()
  return useQuery({
    queryKey: ['reviewSummary', selectedBikeId],
    queryFn: () => fetchReviewSummary(selectedBikeId!),
    enabled: !!selectedBikeId,
  })
}

// ---------------------------------------------------------------------------
// Review list (reusable — used by ReviewsTab and InsightsTab)
// ---------------------------------------------------------------------------
export function ReviewList() {
  const { selectedBikeId } = useSelectedBike()
  const reviewsQ = useQuery({
    queryKey: ['reviews', selectedBikeId],
    queryFn: () => fetchReviews(selectedBikeId!),
    enabled: !!selectedBikeId,
  })

  const reviews = reviewsQ.data ?? []
  const empty = !reviewsQ.isLoading && reviews.length === 0

  if (reviewsQ.isLoading) {
    return (
      <div className="flex flex-col gap-3">
        {[0, 1, 2].map(i => <Card key={i} className="h-32 animate-pulse" />)}
      </div>
    )
  }
  if (empty) {
    return (
      <Card className="p-12 text-center">
        <p className="text-muted-foreground">
          No reviews yet — click <strong className="text-foreground">Refresh Reviews</strong> to fetch them from BikeWale.
        </p>
      </Card>
    )
  }
  return (
    <div className="flex flex-col gap-3">
      {reviews.map(r => <ReviewCard key={r.post_id} review={r} />)}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Standalone Reviews tab — kept for backwards-compat. The Insights tab is the
// new home for owner reviews going forward.
// ---------------------------------------------------------------------------
export function ReviewsTab() {
  const summaryQ = useReviewSummary()
  const summary = summaryQ.data

  return (
    <div className="flex flex-col gap-6">
      {summary ? (
        <SummaryCards summary={summary} />
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {[0, 1, 2].map(i => <Card key={i} className="h-24 animate-pulse" />)}
        </div>
      )}

      <div className="flex justify-end">
        <ReviewRefreshButton />
      </div>

      <ReviewList />
    </div>
  )
}
