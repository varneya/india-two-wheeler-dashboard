import { useQueryClient } from '@tanstack/react-query'
import { Loader2, RefreshCw } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { fetchRefreshStatus, triggerRefresh } from '../api/salesApi'
import { useSelectedBike } from '../context/SelectedBike'
import { Button } from './ui/button'

export function RefreshButton() {
  const queryClient = useQueryClient()
  const { selectedBikeId } = useSelectedBike()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const baselineRef = useRef<string | null>(null)

  function stopPolling() {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }

  async function handleRefresh() {
    setLoading(true)
    setError(null)
    try {
      const status = await fetchRefreshStatus()
      baselineRef.current = status.run_at
      await triggerRefresh(selectedBikeId)

      pollRef.current = setInterval(async () => {
        try {
          const latest = await fetchRefreshStatus()
          if (latest.run_at !== baselineRef.current) {
            stopPolling()
            setLoading(false)
            queryClient.invalidateQueries({ queryKey: ['sales', selectedBikeId] })
            queryClient.invalidateQueries({ queryKey: ['metrics', selectedBikeId] })
            queryClient.invalidateQueries({ queryKey: ['bikes'] })
          }
        } catch {
          stopPolling()
          setLoading(false)
        }
      }, 3000)
    } catch (e) {
      setLoading(false)
      setError('Refresh failed — is the backend running?')
    }
  }

  useEffect(() => () => stopPolling(), [])

  return (
    <div className="flex items-center gap-3">
      <Button onClick={handleRefresh} disabled={loading}>
        {loading ? <Loader2 className="animate-spin" /> : <RefreshCw />}
        {loading ? 'Scraping…' : 'Refresh Data'}
      </Button>
      {error && <p className="text-destructive text-sm">{error}</p>}
    </div>
  )
}
