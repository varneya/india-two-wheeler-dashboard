import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchHardware } from '../../api/themesApi'
import type { HardwareReport } from '../../types/themes'

export function useThemesHardware() {
  const [hw, setHw] = useState<HardwareReport | null>(null)
  const [hwLoading, setHwLoading] = useState(true)
  const [hwError, setHwError] = useState<string | null>(null)
  const requestsRef = useRef({ generation: 0 })
  const mountedRef = useRef(false)

  const refreshHw = useCallback(() => {
    // A model pull can finish after the hardware panel has unmounted.
    if (!mountedRef.current) return
    const requests = requestsRef.current
    const generation = ++requests.generation
    const isCurrent = () => mountedRef.current && generation === requests.generation
    return fetchHardware()
      .then(report => {
        if (isCurrent()) {
          setHw(report)
          setHwError(null)
        }
      })
      .catch(error => {
        if (isCurrent()) setHwError(error instanceof Error ? error.message : String(error))
      })
      .finally(() => {
        if (isCurrent()) setHwLoading(false)
      })
  }, [])

  useEffect(() => {
    const requests = requestsRef.current
    mountedRef.current = true
    void refreshHw()
    return () => {
      mountedRef.current = false
      ++requests.generation
    }
  }, [refreshHw])

  return { hw, hwLoading, hwError, refreshHw }
}
