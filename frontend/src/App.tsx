import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { Moon, Sun } from 'lucide-react'
import { useEffect, useState } from 'react'
import { API_BASE } from './api/client'
import { fetchBikes } from './api/bikesApi'
import { BikeCommandPalette } from './components/BikeCommandPalette'
import { BikePicker } from './components/BikePicker'
import { CompareTab } from './components/CompareTab'
import { InsightsTab } from './components/InsightsTab'
import { MetricsCards } from './components/MetricsCards'
import { RefreshButton } from './components/RefreshButton'
import { ForecastTab } from './components/ForecastTab'
import { RefreshTab } from './components/RefreshTab'
import { SalesChart } from './components/SalesChart'
import { SalesTable } from './components/SalesTable'
import { SetupTab } from './components/SetupTab'
import { StatusBanner } from './components/StatusBanner'
import { SourceComparisonCard } from './components/SourceComparisonCard'
import { Badge } from './components/ui/badge'
import { Card } from './components/ui/card'
import { Button } from './components/ui/button'
import { Toaster } from './components/ui/sonner'
import { Tabs, TabsList, TabsTrigger } from './components/ui/tabs'
import { SelectedBikeProvider, useSelectedBike } from './context/SelectedBike'
import { useSalesData } from './hooks/useSalesData'
import { useTheme } from './hooks/useTheme'

// Brand IDs known to the catalogue. We use this to derive the brand prefix
// from a bike_id without an extra API call.
const KNOWN_BRAND_IDS = [
  'royal-enfield', 'harley-davidson',
  'yamaha', 'honda', 'hero', 'bajaj', 'tvs', 'suzuki', 'ktm',
  'aprilia', 'kawasaki', 'triumph', 'ducati', 'bmw', 'husqvarna',
]
function brandIdFromBikeId(bikeId: string): string | null {
  for (const b of KNOWN_BRAND_IDS) {
    if (bikeId === b || bikeId.startsWith(b + '-')) return b
  }
  return null
}

const queryClient = new QueryClient()

type Tab = 'sales' | 'insights' | 'compare' | 'forecast' | 'refresh' | 'setup'

const TAB_LABELS: Record<Tab, string> = {
  sales: 'Sales Data',
  insights: 'Owner Insights',
  compare: 'Compare',
  forecast: 'Forecast',
  refresh: 'Data Refresh',
  setup: 'Setup',
}

const TAB_ORDER: Tab[] = ['sales', 'insights', 'compare', 'forecast', 'refresh', 'setup']

function ThemeToggle() {
  const { theme, toggle } = useTheme()
  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={toggle}
      aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
      title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
    >
      {theme === 'dark' ? <Sun /> : <Moon />}
    </Button>
  )
}

function Dashboard() {
  const [tab, setTab] = useState<Tab>('sales')
  const { selectedBikeId } = useSelectedBike()
  const { sales, metrics, isLoading, isError } = useSalesData(selectedBikeId)

  // On first load, probe the backend. If unreachable, jump to the Setup tab so
  // visitors landing on the hosted page see install instructions instead of a
  // broken-looking dashboard.
  useEffect(() => {
    let cancelled = false
    fetch(`${API_BASE}/health`, { cache: 'no-store' })
      .then(r => {
        if (!cancelled && !r.ok) setTab('setup')
      })
      .catch(() => {
        if (!cancelled) setTab('setup')
      })
    return () => {
      cancelled = true
    }
  }, [])

  // Fetch the bikes list so we can show the selected bike's brand chip
  const { data: bikes = [] } = useQuery({ queryKey: ['bikes'], queryFn: fetchBikes })
  const selectedBike = bikes.find(b => b.id === selectedBikeId)

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="max-w-5xl mx-auto px-4 py-8 flex flex-col gap-6">

        {/* App heading */}
        <div className="flex flex-col gap-1">
          <h1 className="text-foreground text-2xl font-bold tracking-tight">
            India Two-Wheeler Sales
          </h1>
          <p className="text-muted-foreground text-sm">
            Monthly sales · owner reviews · theme analysis
          </p>
        </div>

        {/* Picker + actions */}
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
          <div className="flex items-center gap-3 flex-wrap">
            <BikePicker />
            {selectedBike && (
              <Badge variant="outline" className="rounded-full">
                {selectedBike.brand}
              </Badge>
            )}
            <kbd className="hidden md:inline-flex h-6 items-center gap-1 rounded border border-border bg-muted px-1.5 text-[10px] font-mono text-muted-foreground">
              <span className="text-xs">⌘</span>K
            </kbd>
          </div>

          <div className="flex items-center gap-3">
            {tab === 'sales' && <RefreshButton />}
            <ThemeToggle />
          </div>
        </div>

        {/* Tabs (Radix-backed). Wrapper allows the list to scroll horizontally
            on narrow viewports instead of clipping the rightmost tab. */}
        <Tabs value={tab} onValueChange={(v) => setTab(v as Tab)}>
          <div className="overflow-x-auto -mx-4 px-4 pb-1">
            <TabsList>
              {TAB_ORDER.map(t => (
                <TabsTrigger key={t} value={t}>
                  {TAB_LABELS[t]}
                </TabsTrigger>
              ))}
            </TabsList>
          </div>
        </Tabs>

        {/* Error banner */}
        {isError && tab === 'sales' && (
          <Card className="border-destructive/50 bg-destructive/10 py-3">
            <div className="px-6 text-destructive text-sm">
              Could not connect to the backend.{' '}
              <button
                type="button"
                onClick={() => setTab('setup')}
                className="underline font-medium hover:opacity-80"
              >
                Open the Setup tab
              </button>{' '}
              for install instructions, or run{' '}
              <code className="bg-destructive/20 px-1 rounded">uvicorn main:app</code> on port 8000.
            </div>
          </Card>
        )}

        {/* Sales tab */}
        {tab === 'sales' && (
          <>
            {isLoading ? (
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                {[0, 1, 2].map(i => (
                  <Card key={i} className="h-24 animate-pulse" />
                ))}
              </div>
            ) : sales.length === 0 ? (
              <Card className="p-12 text-center">
                <p className="text-muted-foreground">
                  No sales data yet for <strong className="text-foreground">{selectedBike?.display_name ?? selectedBikeId}</strong>.
                </p>
                <p className="text-muted-foreground/70 text-sm mt-2">
                  Click <strong className="text-foreground">Refresh Data</strong> to scrape RushLane for this bike.
                </p>
              </Card>
            ) : (
              <>
                <MetricsCards
                  metrics={metrics}
                  sales={sales}
                  launchMonth={selectedBike?.launch_month}
                />
                <SalesChart sales={sales} displayName={selectedBike?.display_name} />
                <SourceComparisonCard brandId={brandIdFromBikeId(selectedBikeId)} />
                <SalesTable sales={sales} />
                <StatusBanner metrics={metrics} />
              </>
            )}
          </>
        )}

        {/* Owner Insights — themes + collapsible raw reviews */}
        {tab === 'insights' && (
          selectedBike && !selectedBike.has_reviews ? (
            <Card className="p-12 text-center">
              <p className="text-muted-foreground">
                BikeWale doesn't have a reviews page for <strong className="text-foreground">{selectedBike.display_name}</strong>, so themes can't be derived.
              </p>
            </Card>
          ) : (
            <InsightsTab />
          )
        )}

        {/* Compare tab */}
        {tab === 'compare' && <CompareTab />}

        {/* Forecast tab */}
        {tab === 'forecast' && <ForecastTab />}

        {/* Data Refresh tab */}
        {tab === 'refresh' && <RefreshTab />}

        {/* Setup tab */}
        {tab === 'setup' && <SetupTab />}
      </div>
    </div>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <SelectedBikeProvider>
        <Dashboard />
        <BikeCommandPalette />
        <Toaster richColors closeButton position="bottom-right" />
      </SelectedBikeProvider>
    </QueryClientProvider>
  )
}
