/**
 * Stats store — dashboard summary statistics (design doc §5.1).
 */
import { create } from 'zustand'
import { statsApi } from '../api/stats'
import type { DashboardStats, ProjectStats } from '../types/api'

interface StatsState {
  summary: DashboardStats | null
  projects: ProjectStats[]
  loading: boolean
  error: string | null
  fetchSummary: () => Promise<void>
  fetchProjects: () => Promise<void>
}

export const useStatsStore = create<StatsState>((set) => ({
  summary: null,
  projects: [],
  loading: false,
  error: null,

  fetchSummary: async () => {
    set({ loading: true, error: null })
    try {
      const summary = await statsApi.getSummary()
      set({ summary, loading: false })
    } catch (err) {
      set({ error: String(err), loading: false })
    }
  },

  fetchProjects: async () => {
    set({ loading: true, error: null })
    try {
      const res = await statsApi.getProjects()
      set({ projects: res.projects, loading: false })
    } catch (err) {
      set({ error: String(err), loading: false })
    }
  },
}))
