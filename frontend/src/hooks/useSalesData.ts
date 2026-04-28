import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import {
  fetchBrandForecast,
  fetchBrandForecastStatus,
  fetchBrandMetrics,
  fetchBrandSalesSeries,
  fetchForecast,
  fetchForecastStatus,
  fetchMetrics,
  fetchSales,
  fetchSalesSeries,
  triggerBrandForecastRefresh,
  triggerForecastRefresh,
  type BrandSecondaryPoint,
  type ForecastResult,
} from '../api/salesApi'
import type { SalesSeriesResponse } from '../types/sales'

const DEFAULT_HORIZON = 6
// Prophet runs on as few as 2 points but the result is meaningless. 4 is the
// floor where the model has at least one MoM transition to learn from. The
// `low_confidence` pill in the chart controls warns when n_observed < 12.
const MIN_OBSERVED_FOR_FORECAST = 4

interface Args {
  bikeId: string | null
  brandId: string | null
}

/**
 * Central data hook for the unified Sales view. Operates in one of two modes:
 *
 *   - **Per-bike** (bikeId set): hits the `/api/bikes/{id}/...` endpoints.
 *   - **Brand-level** (bikeId null, brandId set): hits the
 *     `/api/brands/{id}/...` endpoints. Returns the same shape so the chart,
 *     metrics card, and controls components don't need to know which mode
 *     they're in.
 *
 * Forecast state (showForecast, horizon, refit, fitting flag) is the same
 * in both modes; the cache key includes the scope so bike + brand entries
 * don't collide in React Query.
 */
export function useSalesData({ bikeId, brandId }: Args) {
  const qc = useQueryClient()
  const [showForecast, setShowForecast] = useState(false)
  const [horizon, setHorizon] = useState(DEFAULT_HORIZON)
  const [forecastFitting, setForecastFitting] = useState(false)

  const isBrandMode = bikeId === null && brandId !== null
  // Stable scope key for React Query namespacing
  const scopeKey = isBrandMode ? `brand:${brandId}` : (bikeId ? `bike:${bikeId}` : null)

  // Reset toggle when the user switches scopes — every scope has its own cache.
  useEffect(() => {
    setShowForecast(false)
    setForecastFitting(false)
  }, [scopeKey])

  // ---------------------------------------------------------------------------
  // Per-bike-only: raw sales rows (used by Compare + the collapsible table)
  // ---------------------------------------------------------------------------
  const salesQuery = useQuery({
    queryKey: ['sales', bikeId],
    queryFn: () => fetchSales(bikeId!),
    enabled: !!bikeId,
  })

  // ---------------------------------------------------------------------------
  // Metrics — bike or brand
  // ---------------------------------------------------------------------------
  const metricsQuery = useQuery({
    queryKey: ['metrics', scopeKey],
    queryFn: () =>
      isBrandMode ? fetchBrandMetrics(brandId!) : fetchMetrics(bikeId!),
    enabled: !!scopeKey,
  })

  // ---------------------------------------------------------------------------
  // Series (cheap, no Prophet) — bike or brand
  // ---------------------------------------------------------------------------
  const seriesQuery = useQuery({
    queryKey: ['sales-series', scopeKey],
    queryFn: async () => {
      if (isBrandMode) {
        const r = await fetchBrandSalesSeries(brandId!)
        return r as unknown as SalesSeriesResponse & {
          secondary_series?: BrandSecondaryPoint[]
        }
      }
      return fetchSalesSeries(bikeId!) as unknown as SalesSeriesResponse & {
        secondary_series?: BrandSecondaryPoint[]
      }
    },
    enabled: !!scopeKey,
  })

  // ---------------------------------------------------------------------------
  // Forecast (lazy) — bike or brand
  // ---------------------------------------------------------------------------
  const forecastQuery = useQuery({
    queryKey: ['forecast', scopeKey, horizon],
    queryFn: async () => {
      const r = isBrandMode
        ? await fetchBrandForecast(brandId!, { horizon })
        : await fetchForecast(bikeId!, { horizon })
      if ('pending' in r) {
        await waitForForecastFit(scopeKey!, isBrandMode)
        const fresh = isBrandMode
          ? await fetchBrandForecast(brandId!, { horizon })
          : await fetchForecast(bikeId!, { horizon })
        if ('pending' in fresh) {
          throw new Error('Forecast fitting did not complete')
        }
        return fresh
      }
      return r
    },
    enabled: !!scopeKey && showForecast,
    staleTime: 5 * 60 * 1000,
  })

  useEffect(() => {
    if (!showForecast) return
    setForecastFitting(forecastQuery.isFetching)
  }, [forecastQuery.isFetching, showForecast])

  async function refit() {
    if (!scopeKey) return
    setForecastFitting(true)
    try {
      if (isBrandMode) {
        await triggerBrandForecastRefresh(brandId!, { horizon })
        await waitForForecastFit(scopeKey, true)
      } else {
        await triggerForecastRefresh(bikeId!, { horizon })
        await waitForForecastFit(scopeKey, false)
      }
      await qc.invalidateQueries({ queryKey: ['forecast', scopeKey, horizon] })
      setShowForecast(true)
    } finally {
      setForecastFitting(false)
    }
  }

  const series = (seriesQuery.data ?? null) as
    | (SalesSeriesResponse & { secondary_series?: BrandSecondaryPoint[] })
    | null
  const forecast: ForecastResult | null =
    showForecast && forecastQuery.data ? forecastQuery.data : null
  const observedCount = series?.history.filter(h => !h.imputed).length ?? 0

  return {
    sales: salesQuery.data ?? [],
    metrics: metricsQuery.data ?? null,
    series,
    forecast,
    observedCount,
    secondarySeries: series?.secondary_series ?? null,
    isBrandMode,

    showForecast,
    setShowForecast,
    horizon,
    setHorizon,
    refit,
    forecastFitting,
    canForecast: observedCount >= MIN_OBSERVED_FOR_FORECAST,

    isLoading:
      (!isBrandMode && salesQuery.isLoading) ||
      metricsQuery.isLoading ||
      seriesQuery.isLoading,
    isError:
      (!isBrandMode && salesQuery.isError) ||
      metricsQuery.isError ||
      seriesQuery.isError,
  }
}

async function waitForForecastFit(
  scopeKey: string,
  isBrand: boolean,
  maxMs = 60_000,
): Promise<void> {
  const id = scopeKey.replace(/^(bike|brand):/, '')
  const start = Date.now()
  while (Date.now() - start < maxMs) {
    const st = isBrand
      ? await fetchBrandForecastStatus(id)
      : await fetchForecastStatus(id)
    if (st.stage === 'done') return
    if (st.stage === 'error') {
      throw new Error(st.error || 'forecast fit failed')
    }
    await new Promise(r => setTimeout(r, 1500))
  }
  throw new Error('forecast fit timed out')
}
