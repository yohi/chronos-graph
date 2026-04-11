import { create } from 'zustand'
import { apiFetch } from '../api/client'

export interface DashboardStats {
  activeCount: number
  archivedCount: number
  totalCount: number
  edgeCount: number
  projectCount: number
  projects: string[]
}

interface StatsState {
  stats: DashboardStats | null
  isLoading: boolean
  error: string | null
  fetchStats: () => Promise<void>
}

export const useStatsStore = create<StatsState>((set) => ({
  stats: null,
  isLoading: false,
  error: null,
  fetchStats: async () => {
    set({ isLoading: true, error: null })
    try {
      const data = await apiFetch<DashboardStats>('/api/stats/summary')
      set({ stats: data, isLoading: false })
    } catch (e) {
      set({ error: e instanceof Error ? e.message : 'Unknown error', isLoading: false })
    }
  },
}))