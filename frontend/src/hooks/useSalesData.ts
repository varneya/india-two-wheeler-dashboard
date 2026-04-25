import { useQuery } from '@tanstack/react-query'
import { fetchMetrics, fetchSales } from '../api/salesApi'

export function useSalesData(bikeId: string) {
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

  return {
    sales: salesQuery.data ?? [],
    metrics: metricsQuery.data ?? null,
    isLoading: salesQuery.isLoading || metricsQuery.isLoading,
    isError: salesQuery.isError || metricsQuery.isError,
  }
}
