import axios from 'axios'
import type { Metrics, RefreshStatus, SalesDataPoint } from '../types/sales'

const api = axios.create({ baseURL: '/api' })

export const fetchSales = (bikeId: string): Promise<SalesDataPoint[]> =>
  api.get<SalesDataPoint[]>(`/bikes/${bikeId}/sales`).then(r => r.data)

export const fetchMetrics = (bikeId: string): Promise<Metrics> =>
  api.get<Metrics>(`/bikes/${bikeId}/metrics`).then(r => r.data)

export const triggerRefresh = (bikeId: string): Promise<void> =>
  api.post(`/bikes/${bikeId}/refresh`).then(() => undefined)

export const fetchRefreshStatus = (): Promise<RefreshStatus> =>
  api.get<RefreshStatus>('/refresh/status').then(r => r.data)
