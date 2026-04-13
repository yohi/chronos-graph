/**
 * Logs API — /api/logs/*
 */
import { apiClient } from './client'
import type { LogsRecentResponse } from '../types/api'

export const logsApi = {
  getRecent: (limit = 100) =>
    apiClient.get<LogsRecentResponse>(`/logs/recent?limit=${limit}`),
}
