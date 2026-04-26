import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import {
  fetchForecast,
  fetchForecastStatus,
  fetchMetrics,
  fetchSales,
  fetchSalesSeries,
  triggerForecastRefresh,
  type ForecastResult,
} from '../api/salesApi'

const DEFAULT_HORIZON = 6
// Prophet runs on as few as 2 points but the result is meaningless. 4 is the
// floor where the model has at least one MoM transition to learn from. The
// `low_confidence` pill in the chart controls warns when n_observed < 12.
const MIN_OBSERVED_FOR_FORECAST = 4

/**
 * Central data hook for the unified Sales view. Returns:
 *   - `sales`        : raw per-source rows (used by SalesTable + Compare)
 *   - `metrics`      : MetricsCards aggregates
 *   - `series`       : canonical monthly time series with imputation marks
 *                      + inline anomaly flags. Always loaded — cheap.
 *   - `forecast`     : Prophet payload (history + forecast + CI). Lazy: only
 *                      loaded when the user toggles "Show forecast" on.
 *   - `forecastFitting` : true while a background fit is in flight
 *   - `showForecast` / `setShowForecast` : controlled toggle for the chart layer
 *   - `horizon` / `setHorizon`           : forecast horizon in months
 *   - `refit`        : kicks off a fresh Prophet fit (used by the Re-fit button)
 *
 * Default-forecast behaviour: if a fresh cached forecast comes back from the
 * first lazy call, the toggle flips on automatically so the user sees their
 * cached prediction without having to click. If the cache is empty, the
 * toggle stays off and the chart renders only the cheap series data.
 */
export function useSalesData(bikeId: string) {
  const qc = useQueryClient()
  const [showForecast, setShowForecast] = useState(false)
  const [horizon, setHorizon] = useState(DEFAULT_HORIZON)
  const [forecastFitting, setForecastFitting] = useState(false)

  // Reset toggle when the user changes bikes — every bike has its own cache state.
  useEffect(() => {
    setShowForecast(false)
    setForecastFitting(false)
  }, [bikeId])

  const salesQuery = useQuery({
    queryKey: ['sales', bikeId],
    queryFn: () => fetchSales(bikeId),
    enabled: !!bikeId,
  })

  const metricsQuery = useQuery({
    queryKey: ['metrics', bikeId],
    queryFn: () => fetchMetrics(bikeId),
    enabled: !!bikeId,
  })

  const seriesQuery = useQuery({
    queryKey: ['sales-series', bikeId],
    queryFn: () => fetchSalesSeries(bikeId),
    enabled: !!bikeId,
  })

  // Auto-probe for a cached forecast on bike change. If one exists, flip the
  // toggle on so the user sees it instantly. If not (the response is `pending`),
  // leave the toggle off — they can opt in via the chart controls.
  useEffect(() => {
    if (!bikeId) return
    let cancelled = false
    fetchForecast(bikeId, { horizon })
      .then(r => {
        if (cancelled) return
        if ('pending' in r) {
          // No fresh cache — the GET kicked off a background fit, but we
          // don't auto-show it. User can click "Show forecast" to wait.
          return
        }
        // Fresh cache: prime React Query and turn the layer on.
        qc.setQueryData(['forecast', bikeId, horizon], r)
        setShowForecast(true)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bikeId, horizon])

  const forecastQuery = useQuery({
    queryKey: ['forecast', bikeId, horizon],
    queryFn: async () => {
      const r = await fetchForecast(bikeId, { horizon })
      if ('pending' in r) {
        // Poll until done, then re-fetch the real payload.
        await waitForForecastFit(bikeId)
        const fresh = await fetchForecast(bikeId, { horizon })
        if ('pending' in fresh) {
          throw new Error('Forecast fitting did not complete')
        }
        return fresh
      }
      return r
    },
    enabled: !!bikeId && showForecast,
    staleTime: 5 * 60 * 1000,
  })

  // Track whether a fit is currently in-flight server-side
  useEffect(() => {
    if (!showForecast) return
    if (!forecastQuery.isFetching) {
      setForecastFitting(false)
      return
    }
    setForecastFitting(true)
  }, [forecastQuery.isFetching, showForecast])

  async function refit() {
    if (!bikeId) return
    setForecastFitting(true)
    try {
      await triggerForecastRefresh(bikeId, { horizon })
      await waitForForecastFit(bikeId)
      // Bust the cache for this bike+horizon and re-fetch.
      await qc.invalidateQueries({ queryKey: ['forecast', bikeId, horizon] })
      setShowForecast(true)
    } finally {
      setForecastFitting(false)
    }
  }

  const series = seriesQuery.data ?? null
  const forecast: ForecastResult | null =
    showForecast && forecastQuery.data ? forecastQuery.data : null
  const observedCount = series?.history.filter(h => !h.imputed).length ?? 0

  return {
    // Raw per-source data + aggregates (unchanged from the old hook)
    sales: salesQuery.data ?? [],
    metrics: metricsQuery.data ?? null,

    // New: enriched monthly series + forecast layer state
    series,
    forecast,
    observedCount,

    // Forecast controls
    showForecast,
    setShowForecast,
    horizon,
    setHorizon,
    refit,
    forecastFitting,
    canForecast: observedCount >= MIN_OBSERVED_FOR_FORECAST,

    // Aggregate loading / error
    isLoading:
      salesQuery.isLoading ||
      metricsQuery.isLoading ||
      seriesQuery.isLoading,
    isError:
      salesQuery.isError ||
      metricsQuery.isError ||
      seriesQuery.isError,
  }
}

async function waitForForecastFit(bikeId: string, maxMs = 60_000): Promise<void> {
  const start = Date.now()
  while (Date.now() - start < maxMs) {
    const st = await fetchForecastStatus(bikeId)
    if (st.stage === 'done') return
    if (st.stage === 'error') {
      throw new Error(st.error || 'forecast fit failed')
    }
    await new Promise(r => setTimeout(r, 1500))
  }
  throw new Error('forecast fit timed out')
}
