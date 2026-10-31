import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { fetchBikes } from '../api/bikesApi'

// ---------------------------------------------------------------------------
// Effective bike derivation for the Themes API.
// ---------------------------------------------------------------------------
// KNOWN_BRAND_IDS used for prefix matching when deriving the brand from a
// bike id. Longest first so 'royal-enfield' beats 'royal'.
const KNOWN_BRAND_IDS = [
  'royal-enfield', 'harley-davidson',
  'yamaha', 'honda', 'hero', 'bajaj', 'tvs', 'suzuki', 'ktm',
  'aprilia', 'kawasaki', 'triumph', 'ducati', 'bmw', 'husqvarna',
] as const

function brandPrefix(bikeId: string): string | null {
  for (const b of KNOWN_BRAND_IDS) {
    if (bikeId === b || bikeId.startsWith(b + '-')) return b
  }
  return null
}

// The Themes API is bike-keyed even when we're running a brand-pool
// analysis (the result needs SOME bike to be saved against). When the
// user is in All mode, fall back to the first bike in the brand that
// has reviews — typically the most popular bike of that brand.
export function useEffectiveBikeId(
  selectedBikeId: string | null,
  selectedBrandId: string | null,
): string | null {
  const { data: allBikes = [] } = useQuery({ queryKey: ['bikes'], queryFn: fetchBikes })
  return useMemo(() => {
    if (selectedBikeId) return selectedBikeId
    if (!selectedBrandId) return null
    const candidates = allBikes.filter(b => brandPrefix(b.id) === selectedBrandId)
    const withReviews = candidates.find(b => b.has_reviews)
    return (withReviews?.id) ?? candidates[0]?.id ?? null
  }, [selectedBikeId, selectedBrandId, allBikes])
}
