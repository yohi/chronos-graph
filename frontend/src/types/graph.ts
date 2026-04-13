/**
 * Cytoscape element type definitions.
 */
import type { GraphNode, GraphEdge } from './api'

export type CytoscapeNode = GraphNode
export type CytoscapeEdge = GraphEdge

export type CytoscapeElement = CytoscapeNode | CytoscapeEdge

export interface CytoscapeElements {
  nodes: CytoscapeNode[]
  edges: CytoscapeEdge[]
}
