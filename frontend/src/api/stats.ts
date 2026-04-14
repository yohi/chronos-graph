/**
 * Stats API — /api/stats/*
 */
import { apiClient } from './client'
import type { DashboardStats, ProjectStats } from '../types/api'

export const statsApi = {
  getSummary: () => apiClient.get<DashboardStats>('/stats/summary'),
  getProjects: () => apiClient.get<ProjectStats[]>('/stats/projects'),
}
