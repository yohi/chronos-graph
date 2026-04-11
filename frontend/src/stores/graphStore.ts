import { create } from 'zustand'
import { apiFetch } from '../api/client'

export interface GraphNode {
  id: string
  label: string
  memoryType: string
  importance: number
  project: string | null
  accessCount: number
  createdAt: string
}

export interface GraphEdge {
  id: string
  source: string
  target: string
  edgeType: string
}

export interface GraphElements {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

interface GraphState {
  elements: GraphElements | null
  isLoading: boolean
  error: string | null
  fetchLayout: (limit?: number) => Promise<void>
}

interface GraphLayoutResponse {
  elements: {
    nodes: GraphNode[]
    edges: GraphEdge[]
  }
  totalNodes: number
  returnedNodes: number
  totalEdges: number
}

export const useGraphStore = create<GraphState>((set) => ({
  elements: null,
  isLoading: false,
  error: null,
  fetchLayout: async (limit = 500) => {
    set({ isLoading: true, error: null })
    try {
      const data = await apiFetch<GraphLayoutResponse>(`/api/graph/layout?limit=${limit}`)
      set({
        elements: {
          nodes: data.elements?.nodes || [],
          edges: data.elements?.edges || [],
        },
        isLoading: false,
      })
    } catch (e) {
      set({ error: e instanceof Error ? e.message : 'Unknown error', isLoading: false })
    }
  },
}))