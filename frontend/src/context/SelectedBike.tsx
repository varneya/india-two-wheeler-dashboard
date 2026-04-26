import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

const STORAGE_KEY = 'selectedBikeId'
const URL_BIKE_PARAM = 'bike'
const URL_BRAND_PARAM = 'brand'
const DEFAULT_BRAND_ID = 'yamaha'

/**
 * Selection state for the dashboard. Two modes:
 *
 *   - **Brand-level (All)**: `selectedBikeId === null` and
 *     `selectedBrandId !== null`. The Sales view shows brand-summed data,
 *     forecast, and the cross-source comparison.
 *
 *   - **Per-bike**: `selectedBikeId` and `selectedBrandId` both set. The
 *     Sales view shows the per-bike chart + metrics.
 *
 * Setting a bike implies its brand (derived in the picker layer). Setting a
 * brand without a bike puts us in All mode.
 */
interface Ctx {
  selectedBikeId: string | null
  selectedBrandId: string | null
  setSelectedBike: (bikeId: string, brandId: string) => void
  setSelectedBrandAll: (brandId: string) => void
}

const SelectedBikeContext = createContext<Ctx | null>(null)

interface InitialState {
  bikeId: string | null
  brandId: string | null
}

function readInitial(): InitialState {
  if (typeof window === 'undefined') {
    return { bikeId: null, brandId: DEFAULT_BRAND_ID }
  }
  // Priority: ?bike= > ?brand= > localStorage > default-brand-All
  const params = new URLSearchParams(window.location.search)
  const bikeFromUrl = params.get(URL_BIKE_PARAM)
  if (bikeFromUrl) {
    return { bikeId: bikeFromUrl, brandId: null /* derived later */ }
  }
  const brandFromUrl = params.get(URL_BRAND_PARAM)
  if (brandFromUrl) {
    return { bikeId: null, brandId: brandFromUrl }
  }
  const stored = localStorage.getItem(STORAGE_KEY)
  if (stored) {
    return { bikeId: stored, brandId: null }
  }
  return { bikeId: null, brandId: DEFAULT_BRAND_ID }
}

function syncUrl(bikeId: string | null, brandId: string | null) {
  if (typeof window === 'undefined') return
  const params = new URLSearchParams(window.location.search)
  if (bikeId) {
    params.set(URL_BIKE_PARAM, bikeId)
    params.delete(URL_BRAND_PARAM)
  } else if (brandId) {
    params.delete(URL_BIKE_PARAM)
    params.set(URL_BRAND_PARAM, brandId)
  } else {
    params.delete(URL_BIKE_PARAM)
    params.delete(URL_BRAND_PARAM)
  }
  const next = `${window.location.pathname}?${params.toString()}`
  if (next === `${window.location.pathname}${window.location.search}`) return
  window.history.replaceState(null, '', next)
}

export function SelectedBikeProvider({ children }: { children: ReactNode }) {
  const initial = readInitial()
  const [selectedBikeId, setBikeIdState] = useState<string | null>(initial.bikeId)
  const [selectedBrandId, setBrandIdState] = useState<string | null>(initial.brandId)

  useEffect(() => {
    if (selectedBikeId) localStorage.setItem(STORAGE_KEY, selectedBikeId)
    syncUrl(selectedBikeId, selectedBrandId)
  }, [selectedBikeId, selectedBrandId])

  // React to back/forward navigation that changes URL params externally
  useEffect(() => {
    function onPopState() {
      const params = new URLSearchParams(window.location.search)
      const bike = params.get(URL_BIKE_PARAM)
      const brand = params.get(URL_BRAND_PARAM)
      if (bike) {
        setBikeIdState(bike)
        // brand will be re-derived by BikePicker when bikes load
      } else if (brand) {
        setBikeIdState(null)
        setBrandIdState(brand)
      }
    }
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  function setSelectedBike(bikeId: string, brandId: string) {
    setBrandIdState(brandId)
    setBikeIdState(bikeId)
  }

  function setSelectedBrandAll(brandId: string) {
    setBrandIdState(brandId)
    setBikeIdState(null)
  }

  return (
    <SelectedBikeContext.Provider
      value={{
        selectedBikeId,
        selectedBrandId,
        setSelectedBike,
        setSelectedBrandAll,
      }}
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
