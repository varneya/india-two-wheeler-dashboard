export type ReviewSource = 'reddit' | 'bikedekho' | 'bikewale' | 'zigwheels'

export interface Review {
  id: number
  source: ReviewSource
  post_id: string
  username?: string
  review_text: string
  overall_rating?: number
  thread_url?: string
  scraped_at: string
}

export interface ReviewSummary {
  total: number
  by_source: Record<string, number>
  avg_rating: number | null
  last_refresh: string | null
}
