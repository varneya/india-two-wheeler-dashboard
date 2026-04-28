import { useQueryClient } from '@tanstack/react-query'
import { Loader2, RefreshCw } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import {
  fetchRefreshAllStatus,
  triggerRefreshAll,
  type RefreshAllStatus,
} from '../api/bikesApi'
import { Badge } from './ui/badge'
import { Button } from './ui/button'
import { Card, CardContent } from './ui/card'

function formatDuration(s: number | null): string {
  if (!s || s < 1) return ''
  if (s < 60) return `${Math.round(s)}s`
  const mins = Math.floor(s / 60)
  const secs = Math.round(s % 60)
  return `${mins}m ${secs}s`
}

function formatRelative(iso: string | null): string {
  if (!iso) return ''
  const t = new Date(iso).getTime()
  const diff = Math.max(0, Date.now() - t)
  if (diff < 60_000) return `${Math.floor(diff / 1000)}s ago`
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} minutes ago`
  return new Date(iso).toLocaleString()
}

function ProgressBar({ percent, active }: { percent: number; active: boolean }) {
  const safe = Math.max(0, Math.min(100, percent))
  return (
    <div className="h-2 w-full bg-slate-900/60 rounded-full overflow-hidden">
      <div
        className={`h-full transition-all duration-500 ease-out ${
          active
            ? 'bg-gradient-to-r from-blue-500 to-cyan-400'
            : safe >= 100
            ? 'bg-gradient-to-r from-emerald-500 to-emerald-400'
            : 'bg-slate-700'
        }`}
        style={{ width: `${Math.max(safe, active ? 2 : 0)}%` }}
      />
    </div>
  )
}

export function RefreshTab() {
  const qc = useQueryClient()
  const [status, setStatus] = useState<RefreshAllStatus | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const previousStageRef = useRef<string>('idle')

  // Load initial state on mount (in case a refresh is already running, e.g.
  // user reloaded the page mid-run)
  useEffect(() => {
    fetchRefreshAllStatus()
      .then(s => {
        setStatus(s)
        if (s.running) startPolling()
      })
      .catch(() => {})
    return () => stopPolling()
  }, [])

  function stopPolling() {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  function startPolling() {
    stopPolling()
    pollRef.current = setInterval(async () => {
      try {
        const s = await fetchRefreshAllStatus()
        setStatus(s)
        // Detect stage transitions to invalidate caches at the right moment
        if (previousStageRef.current !== s.stage) {
          if (
            s.stage === 'reviews' ||
            s.stage === 'other_sources' ||
            s.stage === 'autopunditz' ||
            s.stage === 'youtube' ||
            s.stage === 'done'
          ) {
            qc.invalidateQueries({ queryKey: ['bikes'] })
            qc.invalidateQueries({ queryKey: ['brands'] })
            qc.invalidateQueries({ queryKey: ['brandModels'] })
            qc.invalidateQueries({ queryKey: ['sales'] })
            qc.invalidateQueries({ queryKey: ['metrics'] })
          }
          if (s.stage === 'done') {
            qc.invalidateQueries({ queryKey: ['reviews'] })
            qc.invalidateQueries({ queryKey: ['reviewSummary'] })
            qc.invalidateQueries({ queryKey: ['source-comparison'] })
            // Toast on successful completion (only if previous stage wasn't already done)
            const dur = s.duration_seconds ? `${Math.round(s.duration_seconds)}s` : ''
            const extraReviews =
              (s.other_sources?.bikedekho_added ?? 0) +
              (s.other_sources?.zigwheels_added ?? 0) +
              (s.other_sources?.reddit_added ?? 0)
            const totalReviews = (s.reviews.reviews_added ?? 0) + extraReviews
            const apModel = s.autopunditz?.model_rows_added ?? 0
            const apBrand = s.autopunditz?.brand_rows_added ?? 0
            toast.success('Data refresh complete', {
              description: `${s.discovery.bikes_found} bikes · ${totalReviews} reviews · ${apModel + apBrand} AutoPunditz rows${dur ? ` · ${dur}` : ''}`,
            })
          }
          if (s.stage === 'error' && s.error) {
            toast.error('Data refresh failed', { description: s.error })
          }
          previousStageRef.current = s.stage
        }
        if (!s.running) stopPolling()
      } catch {
        stopPolling()
      }
    }, 1500)
  }

  async function handleRefresh(force = false) {
    setError(null)
    setSubmitting(true)
    try {
      const r = await triggerRefreshAll({ force })
      if (r.status === 'already_running') {
        // Just attach to the existing run
      }
      const s = await fetchRefreshAllStatus()
      setStatus(s)
      previousStageRef.current = s.stage
      startPolling()
    } catch (e) {
      setError(`Failed to start refresh: ${e}`)
    } finally {
      setSubmitting(false)
    }
  }

  // ---------------------------------------------------------------------------
  // Derived progress values
  // ---------------------------------------------------------------------------
  const isRunning = !!status?.running
  const isDone = status?.stage === 'done'
  const isError = status?.stage === 'error'
  const stage = status?.stage ?? 'idle'

  // Stage 1 — discovery
  const dUrlsTotal = status?.discovery.urls_total ?? 0
  const dUrlsDone = status?.discovery.urls_done ?? 0
  const dBikes = status?.discovery.bikes_found ?? 0
  const dPercent = dUrlsTotal > 0 ? (dUrlsDone / dUrlsTotal) * 100 : 0
  const stage1Active = stage === 'discovering'
  const stage1Complete = ['reviews', 'other_sources', 'autopunditz', 'youtube', 'done'].includes(stage)
  const stage1Percent = stage1Complete ? 100 : dPercent

  // Stage 2 — reviews (BikeWale)
  const rTotal = status?.reviews.bikes_total ?? 0
  const rDone = status?.reviews.bikes_done ?? 0
  const rCurrent = status?.reviews.current_bike
  const rAdded = status?.reviews.reviews_added ?? 0
  const stage2Active = stage === 'reviews'
  const stage2Complete = ['other_sources', 'autopunditz', 'youtube', 'done'].includes(stage)
  const stage2Percent =
    stage2Complete ? 100 : rTotal > 0 ? (rDone / rTotal) * 100 : 0

  // Stage 3 — additional review sources (BikeDekho + ZigWheels + Reddit)
  const oTotal = status?.other_sources?.bikes_total ?? 0
  const oDone = status?.other_sources?.bikes_done ?? 0
  const oCurrent = status?.other_sources?.current_bike
  const oBikedekho = status?.other_sources?.bikedekho_added ?? 0
  const oZigwheels = status?.other_sources?.zigwheels_added ?? 0
  const oReddit = status?.other_sources?.reddit_added ?? 0
  const oTotalAdded = oBikedekho + oZigwheels + oReddit
  const stage3Active = stage === 'other_sources'
  const stage3Complete = ['autopunditz', 'youtube', 'done'].includes(stage)
  const stage3Percent =
    stage3Complete ? 100 : oTotal > 0 ? (oDone / oTotal) * 100 : 0

  // Stage 4 — AutoPunditz (per-bike prose + brand-level aggregate posts)
  const apPostsTotal = status?.autopunditz?.posts_total ?? 0
  const apPostsDone = status?.autopunditz?.posts_done ?? 0
  const apModelRows = status?.autopunditz?.model_rows_added ?? 0
  const apBrandRows = status?.autopunditz?.brand_rows_added ?? 0
  const stage4Active = stage === 'autopunditz'
  const stage4Complete = ['youtube', 'done'].includes(stage)
  const stage4Percent =
    stage4Complete ? 100 : apPostsTotal > 0 ? (apPostsDone / apPostsTotal) * 100 : 0

  // Stage 5 — YouTube transcripts (per-channel)
  const ytChannelsTotal = status?.youtube?.channels_total ?? 0
  const ytChannelsDone = status?.youtube?.channels_done ?? 0
  const ytCurrentChannel = status?.youtube?.current_channel
  const ytVideosKept = status?.youtube?.videos_kept ?? 0
  const ytShadowRows = status?.youtube?.shadow_rows_added ?? 0
  const stage5Active = stage === 'youtube'
  const stage5Complete = stage === 'done'
  const stage5Percent =
    stage5Complete ? 100 : ytChannelsTotal > 0 ? (ytChannelsDone / ytChannelsTotal) * 100 : 0

  // Per-stage HTTP cache counters: "N cached / M fetched". Hidden when both
  // are zero (idle / pre-stage). Cached count = URLs that 304'd or had a
  // matching content hash; fetched count = URLs whose body was new.
  function cacheCounter(s: { cached?: number; fetched?: number } | undefined) {
    const cached = s?.cached ?? 0
    const fetched = s?.fetched ?? 0
    if (!cached && !fetched) return null
    return (
      <span className="text-xs text-slate-500 font-mono tabular-nums">
        {cached > 0 && (
          <span className="text-emerald-400/80">{cached} cached</span>
        )}
        {cached > 0 && fetched > 0 && ' · '}
        {fetched > 0 && (
          <span className="text-cyan-400/80">{fetched} fetched</span>
        )}
      </span>
    )
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------
  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardContent className="space-y-5">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h2 className="text-lg font-semibold text-foreground">Data Refresh</h2>
            <p className="text-muted-foreground text-sm mt-1">
              Re-scrape AutoPunditz + RushLane wholesale, owner reviews, and YouTube transcripts.
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <Button
              onClick={() => handleRefresh(false)}
              disabled={isRunning || submitting}
              size="lg"
            >
              {isRunning ? <Loader2 className="animate-spin" /> : <RefreshCw />}
              {isRunning ? 'Refreshing…' : 'Refresh Everything'}
            </Button>
            <Button
              onClick={() => handleRefresh(true)}
              disabled={isRunning || submitting}
              size="lg"
              variant="secondary"
              title="Bypass the HTTP cache and re-fetch every URL from scratch. Use after upstream corrections."
            >
              Force re-fetch
            </Button>
          </div>
        </div>

        {/* Idle hint */}
        {stage === 'idle' && !isRunning && (
          <p className="text-sm text-slate-500">
            Click the button above. Discovery + reviews for ~40 bikes typically takes 5–10 minutes.
          </p>
        )}

        {/* Last completion footer */}
        {isDone && status?.finished_at && (
          <div className="bg-emerald-900/25 border border-emerald-700/50 rounded-lg px-4 py-3 text-sm">
            <p className="text-emerald-300 font-medium">
              ✓ Refresh complete{' '}
              <span className="text-emerald-400/70">
                · {formatDuration(status.duration_seconds)}
              </span>
            </p>
            <p className="text-emerald-300/70 text-xs mt-1">
              {dBikes} bikes catalogued · {rAdded} reviews added · finished{' '}
              {formatRelative(status.finished_at)}
            </p>
          </div>
        )}

        {/* Error footer */}
        {isError && status?.error && (
          <div className="bg-red-900/30 border border-red-700/50 rounded-lg px-4 py-3 text-sm">
            <p className="text-red-300 font-medium">Refresh failed</p>
            <p className="text-red-300/70 text-xs mt-1 font-mono">{status.error}</p>
          </div>
        )}

        {error && (
          <div className="bg-red-900/30 border border-red-700/50 rounded-lg px-4 py-3 text-sm text-red-300">
            {error}
          </div>
        )}

        {/* Stage 1 — discovery */}
        {(isRunning || isDone || isError) && (
          <div className="space-y-2">
            <div className="flex items-center justify-between text-sm">
              <div className="flex items-center gap-2">
                <Badge
                  variant={stage1Complete ? 'success' : stage1Active ? 'info' : 'secondary'}
                  className="rounded-full"
                >
                  Stage 1 / 5
                </Badge>
                <span className="text-white font-medium">Discovering bikes from RushLane</span>
                {stage1Active && status?.discovery.stage && (
                  <span className="text-xs text-slate-400">· {status.discovery.stage}</span>
                )}
              </div>
              <div className="flex items-center gap-3">
                <span className="text-xs text-slate-400 font-mono tabular-nums">
                  {stage1Complete
                    ? `${dBikes} bikes parsed`
                    : dUrlsTotal > 0
                    ? `${dUrlsDone}/${dUrlsTotal} articles · ${dBikes} bikes`
                    : '…'}
                </span>
                {cacheCounter(status?.discovery)}
              </div>
            </div>
            <ProgressBar percent={stage1Percent} active={stage1Active} />
          </div>
        )}

        {/* Stage 2 — reviews */}
        {(isRunning || isDone || isError) && (
          <div className="space-y-2">
            <div className="flex items-center justify-between text-sm">
              <div className="flex items-center gap-2 min-w-0">
                <Badge
                  variant={stage2Complete ? 'success' : stage2Active ? 'info' : 'secondary'}
                  className="rounded-full"
                >
                  Stage 2 / 5
                </Badge>
                <span className="text-white font-medium">Refreshing BikeWale reviews</span>
                {stage2Active && rCurrent && (
                  <span className="text-xs text-slate-400 truncate">· {rCurrent}</span>
                )}
              </div>
              <div className="flex items-center gap-3">
                <span className="text-xs text-slate-400 font-mono tabular-nums">
                  {stage2Complete
                    ? `${rAdded} reviews added`
                    : rTotal > 0
                    ? `${rDone}/${rTotal} bikes · ${rAdded} reviews`
                    : 'queued'}
                </span>
                {cacheCounter(status?.reviews)}
              </div>
            </div>
            <ProgressBar percent={stage2Percent} active={stage2Active} />
          </div>
        )}

        {/* Stage 3 — additional review sources */}
        {(isRunning || isDone || isError) && (
          <div className="space-y-2">
            <div className="flex items-center justify-between text-sm">
              <div className="flex items-center gap-2 min-w-0">
                <Badge
                  variant={stage3Complete ? 'success' : stage3Active ? 'info' : 'secondary'}
                  className="rounded-full"
                >
                  Stage 3 / 5
                </Badge>
                <span className="text-white font-medium">BikeDekho · ZigWheels · Reddit</span>
                {stage3Active && oCurrent && (
                  <span className="text-xs text-slate-400 truncate">· {oCurrent}</span>
                )}
              </div>
              <div className="flex items-center gap-3">
                <span className="text-xs text-slate-400 font-mono tabular-nums">
                  {stage3Complete
                    ? `${oTotalAdded} reviews added (BD ${oBikedekho} · ZW ${oZigwheels} · RD ${oReddit})`
                    : oTotal > 0
                    ? `${oDone}/${oTotal} bikes · ${oTotalAdded} reviews`
                    : 'queued'}
                </span>
                {cacheCounter(status?.other_sources)}
              </div>
            </div>
            <ProgressBar percent={stage3Percent} active={stage3Active} />
          </div>
        )}

        {/* Stage 4 — AutoPunditz */}
        {(isRunning || isDone || isError) && (
          <div className="space-y-2">
            <div className="flex items-center justify-between text-sm">
              <div className="flex items-center gap-2 min-w-0">
                <Badge
                  variant={stage4Complete ? 'success' : stage4Active ? 'info' : 'secondary'}
                  className="rounded-full"
                >
                  Stage 4 / 5
                </Badge>
                <span className="text-white font-medium">Scraping AutoPunditz posts</span>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-xs text-slate-400 font-mono tabular-nums">
                  {stage4Complete
                    ? `${apModelRows} model · ${apBrandRows} brand rows`
                    : apPostsTotal > 0
                    ? `${apPostsDone}/${apPostsTotal} posts · ${apModelRows + apBrandRows} rows`
                    : 'queued'}
                </span>
                {cacheCounter(status?.autopunditz)}
              </div>
            </div>
            <ProgressBar percent={stage4Percent} active={stage4Active} />
          </div>
        )}

        {/* Stage 5 — YouTube transcripts */}
        {(isRunning || isDone || isError) && (
          <div className="space-y-2">
            <div className="flex items-center justify-between text-sm">
              <div className="flex items-center gap-2 min-w-0">
                <Badge
                  variant={stage5Complete ? 'success' : stage5Active ? 'info' : 'secondary'}
                  className="rounded-full"
                >
                  Stage 5 / 5
                </Badge>
                <span className="text-white font-medium">Pulling YouTube transcripts</span>
                {stage5Active && ytCurrentChannel && (
                  <span className="text-xs text-slate-400 truncate">· {ytCurrentChannel}</span>
                )}
              </div>
              <div className="flex items-center gap-3">
                <span className="text-xs text-slate-400 font-mono tabular-nums">
                  {stage5Complete
                    ? `${ytVideosKept} videos · ${ytShadowRows} shadow rows`
                    : ytChannelsTotal > 0
                    ? `${ytChannelsDone}/${ytChannelsTotal} channels · ${ytVideosKept} videos`
                    : 'queued'}
                </span>
                {cacheCounter(status?.youtube)}
              </div>
            </div>
            <ProgressBar percent={stage5Percent} active={stage5Active} />
          </div>
        )}
        </CardContent>
      </Card>

      {/* Footnote */}
      <p className="text-xs text-muted-foreground leading-relaxed">
        Stage 1 discovers bikes from RushLane's monthly sales-breakup articles.
        Stage 2 scrapes BikeWale's per-bike reviews; Stage 3 layers in BikeDekho
        user reviews (with ratings), ZigWheels user reviews, and relevant
        comments from <a className="underline" href="https://www.reddit.com/r/IndianBikes/" target="_blank" rel="noreferrer">r/IndianBikes</a>.
        Stage 4 pulls per-brand prose (per-model rows) and monthly aggregate
        posts (brand-level totals) from <a className="underline" href="https://www.autopunditz.com/two-wheeler-sales-figures" target="_blank" rel="noreferrer">AutoPunditz</a> —
        the primary brand-level source. Stage 5 pulls English auto-captions
        from 13 Indian motorcycle YouTube channels (Autocar India, PowerDrift,
        MotorBeam, Gagan Choudhary, Dino's Vault, Strell, MotorInc, Auto Yogi,
        Bike with Girl, BikeDekho, BikeWale, ZigWheels, EVO India) for the
        Influencer Reviews tab. Theme analysis is not auto-rerun — open the
        Theme Analysis tab and click Run for a specific bike.
      </p>
    </div>
  )
}
