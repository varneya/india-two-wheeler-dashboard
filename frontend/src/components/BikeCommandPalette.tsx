import { useQuery } from '@tanstack/react-query'
import { Bike } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { fetchBikes } from '../api/bikesApi'
import { useSelectedBike } from '../context/SelectedBike'
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandShortcut,
} from './ui/command'

function formatUnits(n: number): string {
  if (n >= 100_000) return `${(n / 100_000).toFixed(1)}L`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  return String(n)
}

export function BikeCommandPalette() {
  const [open, setOpen] = useState(false)
  const { setSelectedBikeId } = useSelectedBike()
  const { data: bikes = [] } = useQuery({ queryKey: ['bikes'], queryFn: fetchBikes })

  // Group by brand for nicer rendering
  const grouped = useMemo(() => {
    const map = new Map<string, typeof bikes>()
    for (const b of bikes) {
      const list = map.get(b.brand) ?? []
      list.push(b)
      map.set(b.brand, list)
    }
    // Sort each brand's bikes by total_units desc
    for (const list of map.values()) list.sort((a, b) => b.total_units - a.total_units)
    return Array.from(map.entries()).sort((a, b) => a[0].localeCompare(b[0]))
  }, [bikes])

  // Bind cmd+k / ctrl+k
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'k' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        setOpen(o => !o)
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  function pick(id: string) {
    setSelectedBikeId(id)
    setOpen(false)
  }

  return (
    <CommandDialog open={open} onOpenChange={setOpen}>
      <CommandInput placeholder="Search bikes…" />
      <CommandList>
        <CommandEmpty>No bikes found.</CommandEmpty>
        {grouped.map(([brand, list]) => (
          <CommandGroup key={brand} heading={brand}>
            {list.map(b => (
              <CommandItem
                key={b.id}
                value={`${b.display_name} ${b.brand} ${b.model}`}
                onSelect={() => pick(b.id)}
              >
                <Bike className="opacity-60" />
                <span>{b.display_name}</span>
                {b.total_units > 0 && (
                  <CommandShortcut>
                    {b.months_tracked}m · {formatUnits(b.total_units)}
                  </CommandShortcut>
                )}
              </CommandItem>
            ))}
          </CommandGroup>
        ))}
      </CommandList>
    </CommandDialog>
  )
}
