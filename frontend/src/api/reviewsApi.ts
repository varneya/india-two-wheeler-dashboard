import axios from 'axios'
import type { Review, ReviewSummary } from '../types/reviews'
import { API_BASE } from './client'

const api = axios.create({ baseURL: API_BASE })

export const fetchReviews = (bikeId: string): Promise<Review[]> =>
  api.get<Review[]>(`/bikes/${bikeId}/reviews`).then(r => r.data)

export const fetchReviewSummary = (bikeId: string): Promise<ReviewSummary> =>
  api.get<ReviewSummary>(`/bikes/${bikeId}/reviews/summary`).then(r => r.data)

export const triggerReviewsRefresh = (bikeId: string): Promise<void> =>
  api.post(`/bikes/${bikeId}/reviews/refresh`).then(() => undefined)

export const fetchReviewsRefreshStatus = () =>
  api.get('/reviews/refresh/status').then(r => r.data)
