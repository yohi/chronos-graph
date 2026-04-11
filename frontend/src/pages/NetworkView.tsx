import { useEffect, useRef } from 'react'
import cytoscape, { Core, ElementDefinition } from 'cytoscape'
import cosebilkent from 'cytoscape-cose-bilkent'
import { useGraphStore } from '../stores/graphStore'

cytoscape.use(cosebilkent)

export default function NetworkView() {
  const containerRef = useRef<HTMLDivElement>(null)
  const cyRef = useRef<Core | null>(null)
  const { elements, isLoading, error, fetchLayout } = useGraphStore()

  useEffect(() => {
    fetchLayout()
  }, [fetchLayout])

  useEffect(() => {
    if (!containerRef.current || !elements) return

    if (cyRef.current) {
      cyRef.current.destroy()
    }

    const nodeElements: ElementDefinition[] = elements.nodes.map((node) => ({
      data: {
        id: node.id,
        label: node.label.length > 30 ? node.label.slice(0, 30) + '...' : node.label,
        memoryType: node.memoryType,
        importance: node.importance,
        project: node.project,
        accessCount: node.accessCount,
        createdAt: node.createdAt,
      },
    }))

    const edgeElements: ElementDefinition[] = elements.edges.map((edge) => ({
      data: {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        edgeType: edge.edgeType,
      },
    }))

    const cy = cytoscape({
      container: containerRef.current,
      elements: [...nodeElements, ...edgeElements],
      style: [
        {
          selector: 'node',
          style: {
            'background-color': '#3b82f6',
            'label': 'data(label)',
            'color': '#6b7280',
            'font-size': '10px',
            'text-valign': 'bottom',
            'text-margin-y': 4,
            'width': 30,
            'height': 30,
          },
        },
        {
          selector: 'node[memoryType="episodic"]',
          style: { 'background-color': '#3b82f6' },
        },
        {
          selector: 'node[memoryType="semantic"]',
          style: { 'background-color': '#10b981' },
        },
        {
          selector: 'node[memoryType="procedural"]',
          style: { 'background-color': '#f59e0b' },
        },
        {
          selector: 'edge',
          style: {
            'width': 2,
            'line-color': '#9ca3af',
            'target-arrow-color': '#9ca3af',
            'target-arrow-shape': 'triangle',
          },
        },
        {
          selector: ':selected',
          style: {
            'background-color': '#6366f1',
            'line-color': '#6366f1',
            'target-arrow-color': '#6366f1',
          },
        },
      ],
      layout: { name: 'cose-bilkent' },
    })

    cy.on('tap', 'node', (evt) => {
      const node = evt.target
      const data = node.data()
      alert(`Memory: ${data.label}\nType: ${data.memoryType}\nProject: ${data.project || 'N/A'}`)
    })

    cyRef.current = cy

    return () => {
      cy.destroy()
    }
  }, [elements])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 text-red-600 dark:text-red-400">
        Error: {error}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Network View</h1>
          <p className="text-gray-500 dark:text-gray-400">Interactive graph visualization</p>
        </div>
        <button
          onClick={() => fetchLayout()}
          className="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors"
        >
          Refresh
        </button>
      </div>

      <div
        ref={containerRef}
        className="w-full h-[600px] bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700"
      />
    </div>
  )
}