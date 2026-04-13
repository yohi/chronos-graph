/**
 * Graph store — nodes, edges, selected state, filters (design doc §4.6).
 */
import { create } from 'zustand'
import { graphApi, type GraphLayoutParams } from '../api/graph'
import type { GraphLayoutResponse, MemoryDetail } from '../types/api'

interface GraphState {
  layoutData: GraphLayoutResponse | null
  selectedNodeId: string | null
  selectedNodeDetail: MemoryDetail | null
  loading: boolean
  error: string | null
  // Actions
  fetchLayout: (params?: GraphLayoutParams) => Promise<void>
  setSelectedNode: (id: string | null) => Promise<void>
  clearSelection: () => void
}

export const useGraphStore = create<GraphState>((set, get) => ({
  layoutData: null,
  selectedNodeId: null,
  selectedNodeDetail: null,
  loading: false,
  error: null,

  fetchLayout: async (params = {}) => {
    set({ loading: true, error: null })
    try {
      const layoutData = await graphApi.getLayout({ limit: 100, ...params })
      set({ layoutData, loading: false })
    } catch (err) {
      set({ error: String(err), loading: false })
    }
  },

  setSelectedNode: async (id) => {
    if (id === null) {
      set({ selectedNodeId: null, selectedNodeDetail: null })
      return
    }
    set({ selectedNodeId: id, selectedNodeDetail: null })
    try {
      const detail = await graphApi.getMemory(id)
      // Check if the selected node ID hasn't changed while fetching
      if (get().selectedNodeId === id) {
        set({ selectedNodeDetail: detail })
      }
    } catch {
      // detail is optional — keep selectedNodeId set
    }
  },

  clearSelection: () => set({ selectedNodeId: null, selectedNodeDetail: null }),
}))
