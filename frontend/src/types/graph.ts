/**
 * Cytoscape element type definitions.
 */
import type { GraphElements } from './api'

export type CytoscapeNode = GraphElements['nodes'][number]
export type CytoscapeEdge = GraphElements['edges'][number]

export type CytoscapeElement = CytoscapeNode | CytoscapeEdge

export type CytoscapeElements = GraphElements
