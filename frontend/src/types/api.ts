/**
 * API response type definitions.
 * Based on design doc §3.4 (DashboardStats, GraphLayoutResponse, etc.)
 */

// --- Stats ---

export interface DashboardStats {
  activeCount: number
  archivedCount: number
  totalCount: number
  edgeCount: number
  projectCount: number
  projects: string[]
}

export interface ProjectStats {
  project: string
  activeCount: number
  archivedCount: number
  totalCount: number
}

// --- Graph ---

export interface GraphNodeData {
  id: string
  label: string
  memoryType: 'episodic' | 'semantic' | 'procedural'
  importance: number
  project?: string
  accessCount?: number
  createdAt?: string
}

export interface GraphEdgeData {
  id: string
  source: string
  target: string
  edgeType: string
}

export interface GraphNode {
  data: GraphNodeData
}

export interface GraphEdge {
  data: GraphEdgeData
}

export interface GraphElements {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export interface GraphLayoutResponse {
  elements: GraphElements
  totalNodes: number
  totalEdges: number
  returnedNodes?: number
}

// --- Memory Detail ---

export interface MemoryDetail {
  id: string
  content: string
  memoryType: 'episodic' | 'semantic' | 'procedural'
  importance: number
  project?: string
  tags?: string[]
  accessCount: number
  createdAt: string
  updatedAt?: string
}

// --- System Config ---

export interface SystemConfig {
  storageBackend: string
  graphBackend: string
  cacheBackend: string
  embeddingProvider: string
  embeddingModel: string
  logLevel: string
  dashboardPort: number
}

// --- Logs ---

export interface LogEntry {
  timestamp: string
  level: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL'
  logger: string
  message: string
}

export interface LogsRecentResponse {
  entries: LogEntry[]
}
