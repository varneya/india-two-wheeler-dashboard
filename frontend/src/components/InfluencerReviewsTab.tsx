import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ExternalLink, Video } from 'lucide-react'
import { useState } from 'react'

import { fetchInfluencerVideos, type InfluencerVideo } from '../api/bikesApi'
import { Badge } from './ui/badge'
import { Card, CardContent } from './ui/card'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from './ui/collapsible'

interface Props {
  bikeId: string | null
  bikeName?: string | null
}

function formatDate(yyyymmdd: string | null): string {
  // yt-dlp's upload_date format is 'YYYYMMDD'
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

/**
 * Per-video card. Title + channel + date are always visible; the full
 * transcript hides behind a Collapsible so the page doesn't render
 * tens of thousands of words on first paint when a bike has many videos.
 */
function VideoCard({ video }: { video: InfluencerVideo }) {
  const [open, setOpen] = useState(false)
  return (
    <Card className="overflow-hidden">
      <CardContent className="space-y-3">
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

        {video.transcript && (
          <Collapsible open={open} onOpenChange={setOpen}>
            <CollapsibleTrigger asChild>
              <button
                type="button"
                className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                {open ? 'Hide' : 'Show'} transcript
                <ChevronDown
                  className={`size-3.5 transition-transform ${open ? 'rotate-180' : ''}`}
                />
              </button>
            </CollapsibleTrigger>
            <CollapsibleContent className="mt-2">
              <div className="rounded-lg border border-border/60 bg-card/40 p-3 text-xs leading-relaxed text-muted-foreground max-h-80 overflow-y-auto">
                {video.transcript}
              </div>
            </CollapsibleContent>
          </Collapsible>
        )}
      </CardContent>
    </Card>
  )
}

/**
 * Influencer Reviews tab — per-bike view of YouTube content from the 13
 * curated motorcycle channels we scrape (Autocar India, PowerDrift,
 * MotorBeam, etc.). Sits beside the consumer-review Owner Insights tab so
 * the two perspectives stay separated: owners on one side, creators on
 * the other.
 */
export function InfluencerReviewsTab({ bikeId, bikeName }: Props) {
  const { data: videos = [], isLoading, isError } = useQuery({
    queryKey: ['influencer-videos', bikeId],
    queryFn: () => fetchInfluencerVideos(bikeId!),
    enabled: !!bikeId,
  })

  if (!bikeId) {
    return (
      <Card className="p-12 text-center">
        <p className="text-muted-foreground">
          Pick a specific bike to see its YouTube reviews.
        </p>
      </Card>
    )
  }

  if (isLoading) {
    return (
      <div className="space-y-3">
        {[0, 1, 2].map(i => (
          <Card key={i} className="h-24 animate-pulse" />
        ))}
      </div>
    )
  }

  if (isError) {
    return (
      <Card className="p-12 text-center">
        <p className="text-muted-foreground">
          Couldn't load influencer videos. Make sure the backend is running.
        </p>
      </Card>
    )
  }

  if (videos.length === 0) {
    return (
      <Card className="p-12 text-center">
        <p className="text-muted-foreground">
          No YouTube reviews yet for{' '}
          <strong className="text-foreground">{bikeName ?? bikeId}</strong>.
        </p>
        <p className="text-muted-foreground/70 text-sm mt-2">
          Click <strong className="text-foreground">Refresh Data</strong> to
          pull recent transcripts from Autocar India, PowerDrift, MotorBeam,
          and 10 other channels.
        </p>
      </Card>
    )
  }

  // Group by channel for a cleaner skim — channels with multiple videos
  // get a single section instead of being scattered in date order.
  const byChannel = new Map<string, InfluencerVideo[]>()
  for (const v of videos) {
    const list = byChannel.get(v.channel_name) ?? []
    list.push(v)
    byChannel.set(v.channel_name, list)
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-foreground">
          Influencer Reviews
        </h2>
        <p className="text-sm text-muted-foreground mt-1">
          {videos.length} {videos.length === 1 ? 'video' : 'videos'} across{' '}
          {byChannel.size} {byChannel.size === 1 ? 'channel' : 'channels'} for{' '}
          <strong className="text-foreground">{bikeName ?? bikeId}</strong>.
          Click any title to watch on YouTube; expand the transcript to read.
        </p>
      </div>

      {Array.from(byChannel.entries()).map(([channelName, channelVideos]) => (
        <div key={channelName} className="space-y-2">
          <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">
            {channelName} <span className="text-muted-foreground/60">· {channelVideos.length}</span>
          </h3>
          <div className="space-y-2">
            {channelVideos.map(v => (
              <VideoCard key={v.video_id} video={v} />
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
