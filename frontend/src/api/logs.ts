/**
 * Logs API — /api/logs/*
 */
import { apiClient } from './client'
import type { LogsRecentResponse } from '../types/api'

export const logsApi = {
  getRecent: (limit = 100) => {
    const sanitizedLimit = Math.max(1, Math.min(1000, Math.floor(limit) || 100))
    return apiClient.get<LogsRecentResponse>(`/logs/recent?limit=${sanitizedLimit}`)
  },
}
