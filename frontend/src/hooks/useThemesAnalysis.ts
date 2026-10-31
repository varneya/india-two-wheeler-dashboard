import { useEffect, useRef, useState } from 'react'
import {
  fetchThemes,
  fetchThemesStatus,
  triggerThemesAnalysis,
  type PoolScope,
} from '../api/themesApi'
import type { ThemesResult } from '../types/themes'

// ---------------------------------------------------------------------------
// Themes analysis state machine: trigger → poll status → fetch result.
// Also loads the last persisted result whenever the effective bike changes.
// ---------------------------------------------------------------------------
interface Args {
  bikeId: string | null
  method: string
  config: Record<string, unknown>
  poolScope: PoolScope
}

export function useThemesAnalysis({ bikeId, method, config, poolScope }: Args) {
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<ThemesResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [stateBikeId, setStateBikeId] = useState(bikeId)

  // Reset selection-owned state during render so the new bike never renders
  // the previous bike's result or running state while waiting for its effect.
  if (stateBikeId !== bikeId) {
    setStateBikeId(bikeId)
    setRunning(false)
    setResult(null)
    setError(null)
  }

  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const requestsRef = useRef({ generation: 0 })
  const runningRef = useRef(false)

  function stopPolling() {
    if (pollRef.current !== null) {
      clearTimeout(pollRef.current)
      pollRef.current = null
    }
  }

  // Load last result whenever the effective bike (per-bike or brand-derived) changes
  useEffect(() => {
    // Capture the stable request controller for this effect's cleanup. Its
    // generation can advance when an analysis supersedes the saved-result load.
    const requests = requestsRef.current
    const generation = ++requests.generation
    stopPolling()
    runningRef.current = false

    if (bikeId) {
      fetchThemes(bikeId)
        .then(r => {
          if (generation === requests.generation && r.themes) setResult(r)
        })
        .catch(() => {})
    }

    return () => {
      // Invalidate pending loads, triggers, status requests and result fetches.
      ++requests.generation
      stopPolling()
      runningRef.current = false
    }
  }, [bikeId])

  async function startAnalysis() {
    if (runningRef.current) return
    const requests = requestsRef.current
    const generation = ++requests.generation
    const isCurrent = () => generation === requests.generation
    stopPolling()
    setError(null)

    if (!bikeId) {
      setError('Pick a model (or a brand with at least one bike) to run themes')
      return
    }
    const analysisBikeId = bikeId

    runningRef.current = true
    setRunning(true)

    function finish() {
      runningRef.current = false
      setRunning(false)
    }

    try {
      await triggerThemesAnalysis(analysisBikeId, method, config, poolScope)
    } catch (e) {
      if (!isCurrent()) return
      setError(String(e))
      finish()
      return
    }
    if (!isCurrent()) return

    // Schedule only after each request settles so slow requests never overlap.
    async function poll() {
      if (!isCurrent()) return
      pollRef.current = null
      try {
        const status = await fetchThemesStatus(analysisBikeId)
        if (!isCurrent()) return
        if (status.running) {
          pollRef.current = setTimeout(poll, 2000)
          return
        }

        // Failed runs can leave a previous successful result in the cache.
        // Read the optional status error before requesting that cached result.
        if (status.error) {
          setResult(null)
          setError(status.error)
          finish()
          return
        }

        const latest = await fetchThemes(analysisBikeId)
        if (!isCurrent()) return
        if (latest.error) {
          setResult(null)
          setError(latest.error)
        } else if (latest.themes) {
          setResult(latest)
        }
        finish()
      } catch (e) {
        if (!isCurrent()) return
        setError(String(e))
        finish()
      }
    }

    pollRef.current = setTimeout(poll, 2000)
  }

  return { running, result, error, startAnalysis }
}
