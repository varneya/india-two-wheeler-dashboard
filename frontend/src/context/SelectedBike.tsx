import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

const STORAGE_KEY = 'selectedBikeId'
const URL_PARAM = 'bike'
const DEFAULT_BIKE_ID = 'yamaha-xsr-155'

interface Ctx {
  selectedBikeId: string
  setSelectedBikeId: (id: string) => void
}

const SelectedBikeContext = createContext<Ctx | null>(null)

function readInitialId(): string {
  if (typeof window === 'undefined') return DEFAULT_BIKE_ID
  // Priority: ?bike=... in URL > localStorage > default
  const params = new URLSearchParams(window.location.search)
  const fromUrl = params.get(URL_PARAM)
  if (fromUrl) return fromUrl
  return localStorage.getItem(STORAGE_KEY) || DEFAULT_BIKE_ID
}

function syncUrlParam(bikeId: string) {
  if (typeof window === 'undefined') return
  const params = new URLSearchParams(window.location.search)
  if (params.get(URL_PARAM) === bikeId) return
  params.set(URL_PARAM, bikeId)
  // Replace state so we don't pollute browser history on every pick
  window.history.replaceState(
    null,
    '',
    `${window.location.pathname}?${params.toString()}`,
  )
}

export function SelectedBikeProvider({ children }: { children: ReactNode }) {
  const [selectedBikeId, setSelectedBikeIdState] = useState<string>(readInitialId)

  useEffect(() => {
    if (!selectedBikeId) return
    localStorage.setItem(STORAGE_KEY, selectedBikeId)
    syncUrlParam(selectedBikeId)
  }, [selectedBikeId])

  // React to back/forward navigation that changes the URL param externally
  useEffect(() => {
    function onPopState() {
      const params = new URLSearchParams(window.location.search)
      const v = params.get(URL_PARAM)
      if (v && v !== selectedBikeId) setSelectedBikeIdState(v)
    }
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [selectedBikeId])

  return (
    <SelectedBikeContext.Provider
      value={{ selectedBikeId, setSelectedBikeId: setSelectedBikeIdState }}
    >
      {children}
    </SelectedBikeContext.Provider>
  )
}

export function useSelectedBike(): Ctx {
  const ctx = useContext(SelectedBikeContext)
  if (!ctx) throw new Error('useSelectedBike must be used inside SelectedBikeProvider')
  return ctx
}
