import { useQuery } from '@tanstack/react-query'
import { ExternalLink, Search, Video } from 'lucide-react'
import { useState } from 'react'

import {
  fetchAllInfluencerVideos,
  fetchInfluencerChannels,
  type InfluencerVideo,
} from '../api/bikesApi'
import { Badge } from './ui/badge'
import { Button } from './ui/button'
import { Card, CardContent } from './ui/card'

function formatDate(yyyymmdd: string | null): string {
  if (!yyyymmdd || yyyymmdd.length !== 8) return ''
  const year = yyyymmdd.slice(0, 4)
  const mon = parseInt(yyyymmdd.slice(4, 6), 10) - 1
  const day = yyyymmdd.slice(6, 8)
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
  return `${months[mon]} ${parseInt(day, 10)}, ${year}`
}

function formatDuration(s: number | null): string {
  if (!s) return ''
  const mins = Math.floor(s / 60)
  const secs = s % 60
  return `${mins}:${String(secs).padStart(2, '0')}`
}

function VideoCard({ video }: { video: InfluencerVideo }) {
  const status = video.transcript_status ?? 'ok'
  return (
    <Card className="overflow-hidden">
      <CardContent>
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap mb-1">
              <Badge variant="secondary" className="rounded-full text-xs gap-1">
                <Video className="size-3" /> {video.channel_name}
              </Badge>
              {video.published_at && (
                <span className="text-xs text-muted-foreground">
                  {formatDate(video.published_at)}
                </span>
              )}
              {video.duration_s ? (
                <span className="text-xs text-muted-foreground">
                  · {formatDuration(video.duration_s)}
                </span>
              ) : null}
              {status === 'rate_limited' && (
                <Badge variant="outline" className="text-[10px]">
                  Transcript pending — retries next refresh
                </Badge>
              )}
              {status === 'no_captions' && (
                <Badge variant="outline" className="text-[10px]">
                  No English captions
                </Badge>
              )}
            </div>
            <h3 className="text-sm font-medium text-foreground leading-snug">
              {video.title}
            </h3>
          </div>
          <a
            href={video.video_url}
            target="_blank"
            rel="noreferrer"
            className="text-xs inline-flex items-center gap-1 text-primary hover:underline shrink-0"
          >
            Watch
            <ExternalLink className="size-3" />
          </a>
        </div>
      </CardContent>
    </Card>
  )
}

interface Props {
  // The dashboard's top picker passes its current selection here. When
  // set (per-bike mode), the listing scopes to videos tagged with that
  // bike_id by default. The user can still click "Show all videos" to
  // browse the full catalogue, then re-scope by clicking the bike chip.
  bikeId?: string | null
  bikeName?: string | null
}

/**
 * Influencer Reviews tab. By default scopes to the bike currently
 * selected at the top of the dashboard (per-bike mode). When no bike
 * is selected (brand "All models" mode), or when the user clicks
 * "Show all videos", lists every captured YouTube video chronologically
 * with channel-chip + free-text filters.
 */
export function InfluencerReviewsTab({
  bikeId = null,
  bikeName = null,
}: Props = {}) {
  const [selectedHandle, setSelectedHandle] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  // When the user explicitly opts out of bike scoping, this overrides
  // the bikeId prop and shows all videos.
  const [showAll, setShowAll] = useState(false)

  const effectiveBikeId = !showAll && bikeId ? bikeId : null

  const { data: channels = [] } = useQuery({
    queryKey: ['influencer-channels'],
    queryFn: fetchInfluencerChannels,
  })

  const { data: videos = [], isLoading, isError } = useQuery({
    queryKey: ['influencer-videos', effectiveBikeId, selectedHandle, query],
    queryFn: () =>
      fetchAllInfluencerVideos({
        channel: selectedHandle ?? undefined,
        bike_id: effectiveBikeId ?? undefined,
        q: query || undefined,
      }),
  })

  const totalAll = channels.reduce((s, c) => s + (c.video_count ?? 0), 0)

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-foreground">
          Influencer Reviews
        </h2>
        {effectiveBikeId ? (
          <p className="text-sm text-muted-foreground mt-1">
            Videos tagged to{' '}
            <strong className="text-foreground">{bikeName ?? bikeId}</strong>.{' '}
            <button
              type="button"
              className="underline hover:text-foreground"
              onClick={() => setShowAll(true)}
            >
              Show all videos
            </button>{' '}
            to browse every channel.
          </p>
        ) : showAll && bikeId ? (
          <p className="text-sm text-muted-foreground mt-1">
            Showing all videos.{' '}
            <button
              type="button"
              className="underline hover:text-foreground"
              onClick={() => setShowAll(false)}
            >
              Re-scope to {bikeName ?? bikeId}
            </button>
            .
          </p>
        ) : (
          <p className="text-sm text-muted-foreground mt-1">
            Latest motorcycle videos from a curated set of Indian YouTube
            channels. Filter by channel or search by keyword.
          </p>
        )}
      </div>

      <Card>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-1.5">
            <Button
              size="sm"
              variant={selectedHandle === null ? 'default' : 'secondary'}
              onClick={() => setSelectedHandle(null)}
              className="rounded-full h-7 px-2.5"
            >
              All channels
              <span className="opacity-60 ml-1">{totalAll}</span>
            </Button>
            {channels.map(ch => {
              if (ch.video_count === 0) return null
              const active = selectedHandle === ch.handle
              return (
                <Button
                  key={ch.handle}
                  size="sm"
                  variant={active ? 'default' : 'secondary'}
                  onClick={() => setSelectedHandle(active ? null : ch.handle)}
                  className="rounded-full h-7 px-2.5"
                >
                  {ch.name}
                  <span className="opacity-60 ml-1">{ch.video_count}</span>
                </Button>
              )
            })}
          </div>

          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground" />
            <input
              type="text"
              placeholder="Search title or description…"
              value={query}
              onChange={e => setQuery(e.target.value)}
              className="w-full bg-background text-foreground placeholder-muted-foreground rounded-md pl-9 pr-3 py-2 text-sm outline-none border border-input focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px]"
            />
          </div>
        </CardContent>
      </Card>

      {isLoading ? (
        <div className="space-y-3">
          {[0, 1, 2].map(i => (
            <Card key={i} className="h-24 animate-pulse" />
          ))}
        </div>
      ) : isError ? (
        <Card className="p-12 text-center">
          <p className="text-muted-foreground">
            Couldn't load videos. Make sure the backend is running.
          </p>
        </Card>
      ) : videos.length === 0 ? (
        <Card className="p-12 text-center">
          <p className="text-muted-foreground">
            {totalAll === 0
              ? "No videos yet — click Refresh Data to pull recent reviews from the curated channels."
              : query
              ? <>No videos match <strong className="text-foreground">{query}</strong>.</>
              : 'No videos for the selected channel.'}
          </p>
        </Card>
      ) : (
        <div className="space-y-2">
          <p className="text-xs text-muted-foreground">
            Showing {videos.length} {videos.length === 1 ? 'video' : 'videos'}
            {selectedHandle && ` from ${channels.find(c => c.handle === selectedHandle)?.name ?? selectedHandle}`}
            {query && <> matching <strong className="text-foreground">{query}</strong></>}
            .
          </p>
          {videos.map(v => (
            <VideoCard key={v.video_id} video={v} />
          ))}
        </div>
      )}
    </div>
  )
}
