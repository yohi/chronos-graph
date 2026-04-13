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
  pendingRequests: number
  fetchSummary: () => Promise<void>
  fetchProjects: () => Promise<void>
}

export const useStatsStore = create<StatsState>((set) => ({
  summary: null,
  projects: [],
  loading: false,
  error: null,
  pendingRequests: 0,

  fetchSummary: async () => {
    set((state) => ({ pendingRequests: state.pendingRequests + 1, loading: true, error: null }))
    try {
      const summary = await statsApi.getSummary()
      set({ summary })
    } catch (err) {
      set({ error: String(err) })
    } finally {
      set((state) => {
        const nextPending = Math.max(0, state.pendingRequests - 1)
        return { pendingRequests: nextPending, loading: nextPending > 0 }
      })
    }
  },

  fetchProjects: async () => {
    set((state) => ({ pendingRequests: state.pendingRequests + 1, loading: true, error: null }))
    try {
      const res = await statsApi.getProjects()
      set({ projects: res.projects })
    } catch (err) {
      set({ error: String(err) })
    } finally {
      set((state) => {
        const nextPending = Math.max(0, state.pendingRequests - 1)
        return { pendingRequests: nextPending, loading: nextPending > 0 }
      })
    }
  },
}))
