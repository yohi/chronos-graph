/**
 * Graph API — /api/graph/*
 */
import { apiClient } from './client'
import type { GraphLayoutResponse, MemoryDetail } from '../types/api'

export interface GraphLayoutParams {
  project?: string
  limit?: number
  orderBy?: 'importance' | 'recency'
}

export const graphApi = {
  getLayout: (params: GraphLayoutParams = {}) => {
    const qs = new URLSearchParams()
    if (params.project) qs.set('project', params.project)
    if (params.limit != null) qs.set('limit', String(params.limit))
    if (params.orderBy) qs.set('order_by', params.orderBy)
    const query = qs.toString() ? `?${qs.toString()}` : ''
    return apiClient.get<GraphLayoutResponse>(`/graph/layout${query}`)
  },
  getMemory: (id: string) => apiClient.get<MemoryDetail>(`/memories/${id}`),
}
