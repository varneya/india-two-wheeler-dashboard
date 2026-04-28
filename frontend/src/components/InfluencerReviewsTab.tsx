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

/**
 * Standalone Influencer Reviews tab. Independent of the global
 * brand/model picker — has its own filter (channel chips + free-text
 * search) and lists every captured YouTube video chronologically. Pulls
 * from the curated motorcycle channels in youtube_scraper.CHANNELS.
 */
export function InfluencerReviewsTab() {
  const [selectedHandle, setSelectedHandle] = useState<string | null>(null)
  const [query, setQuery] = useState('')

  // Channels endpoint already returns video_count per channel — no need
  // to pull the full list just to compute filter-chip counts.
  const { data: channels = [] } = useQuery({
    queryKey: ['influencer-channels'],
    queryFn: fetchInfluencerChannels,
  })

  const { data: videos = [], isLoading, isError } = useQuery({
    queryKey: ['influencer-videos', selectedHandle, query],
    queryFn: () =>
      fetchAllInfluencerVideos({
        channel: selectedHandle ?? undefined,
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
        <p className="text-sm text-muted-foreground mt-1">
          Latest motorcycle videos from a curated set of Indian YouTube
          channels. Filter by channel or search by keyword.
        </p>
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
