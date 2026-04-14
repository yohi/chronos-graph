import { useEffect, useRef, useCallback } from 'react'
import cytoscape from 'cytoscape'
// @ts-expect-error — no type definitions for cytoscape-cose-bilkent
import coseBilkent from 'cytoscape-cose-bilkent'
import { useGraphStore } from '../stores/graphStore'

cytoscape.use(coseBilkent)

export default function NetworkView() {
  const containerRef = useRef<HTMLDivElement>(null)
  const cyRef = useRef<cytoscape.Core | null>(null)
  const { layoutData, loading, error, fetchLayout, setSelectedNode, selectedNodeId, selectedNodeDetail, clearSelection } = useGraphStore()

  useEffect(() => {
    fetchLayout()
  }, [fetchLayout])

  const buildGraph = useCallback(() => {
    if (!layoutData || !containerRef.current) return

    if (cyRef.current) {
      cyRef.current.destroy()
    }

    cyRef.current = cytoscape({
      container: containerRef.current,
      elements: layoutData.elements,
      style: [
        {
          selector: 'node',
          style: {
            'background-color': '#666',
            label: 'data(label)',
            'font-size': '10px',
            'text-valign': 'center',
            'text-halign': 'center',
            color: '#fff',
            'text-outline-width': 1,
            'text-outline-color': '#666',
            width: 'mapData(importance, 0, 1, 20, 50)',
            height: 'mapData(importance, 0, 1, 20, 50)',
          },
        },
        {
          selector: 'node[memoryType="episodic"]',
          style: { 'background-color': '#3B82F6', 'text-outline-color': '#3B82F6' },
        },
        {
          selector: 'node[memoryType="semantic"]',
          style: { 'background-color': '#10B981', 'text-outline-color': '#10B981' },
        },
        {
          selector: 'node[memoryType="procedural"]',
          style: { 'background-color': '#F59E0B', 'text-outline-color': '#F59E0B' },
        },
        {
          selector: 'node:selected',
          style: { 'border-width': 3, 'border-color': '#F59E0B' },
        },
        {
          selector: 'edge',
          style: {
            width: 2,
            'line-color': '#ccc',
            'target-arrow-color': '#ccc',
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
            label: 'data(edgeType)',
            'font-size': '8px',
            'text-rotation': 'autorotate',
            'text-margin-y': -10,
          },
        },
      ],
      layout: {
        name: 'cose-bilkent',
        animate: true,
        randomize: true,
      } as cytoscape.LayoutOptions,
    })

    // Node click → graphStore.setSelectedNode (design doc §5.2)
    cyRef.current.on('tap', 'node', (evt) => {
      const id = evt.target.id() as string
      void setSelectedNode(id)
    })
    cyRef.current.on('tap', (evt) => {
      if (evt.target === cyRef.current) {
        void setSelectedNode(null)
      }
    })
  }, [layoutData, setSelectedNode])

  useEffect(() => {
    buildGraph()
    return () => {
      cyRef.current?.destroy()
      cyRef.current = null
    }
  }, [buildGraph])

  const isTruncated =
    layoutData != null &&
    layoutData.returnedNodes != null &&
    layoutData.totalNodes > layoutData.returnedNodes

  return (
    <div className="p-8 h-full flex flex-col">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Network View</h2>
        <div className="text-sm text-gray-500">
          {layoutData
            ? `Showing ${layoutData.returnedNodes ?? layoutData.elements.nodes.length} / ${layoutData.totalNodes} memories`
            : 'Showing top 500 memories by importance'}
        </div>
      </div>

      {/* Truncation warning banner (design doc §4.3) */}
      {isTruncated && (
        <div className="mb-4 px-4 py-2 rounded bg-amber-100 dark:bg-amber-900 text-amber-800 dark:text-amber-200 text-sm">
          Showing {layoutData!.returnedNodes} of {layoutData!.totalNodes} memories.
          Only top memories by importance are rendered. Try filtering by project to see more details.
        </div>
      )}

      <div className="flex-1 flex gap-4 overflow-hidden">
        {/* Graph canvas */}
        <div className="flex-1 bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-700 relative overflow-hidden">
          {loading && (
            <div className="absolute inset-0 flex items-center justify-center bg-white/50 dark:bg-black/50 z-10">
              <p>Loading graph...</p>
            </div>
          )}
          {error && (
            <div className="absolute inset-0 flex items-center justify-center bg-white/50 dark:bg-black/50 z-10">
              <p className="text-red-500">Error: {error}</p>
            </div>
          )}
          <div ref={containerRef} className="w-full h-full" data-testid="network-graph" />
        </div>

        {/* NodeDetailPanel — selectedNodeId がある場合のみ表示 */}
        {selectedNodeId && (
          <div
            data-testid="node-detail-panel"
            className="w-80 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4 overflow-auto flex-shrink-0"
          >
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-semibold">Node Detail</h3>
              <button
                onClick={clearSelection}
                aria-label="Close detail panel"
                className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-500"
              >
                ✕
              </button>
            </div>
            {selectedNodeDetail ? (
              <div className="space-y-3 text-sm">
                <div>
                  <p className="text-gray-500 uppercase text-xs font-medium">Content</p>
                  <p className="mt-1">{selectedNodeDetail.content}</p>
                </div>
                <div>
                  <p className="text-gray-500 uppercase text-xs font-medium">Type</p>
                  <p className="mt-1 capitalize">{selectedNodeDetail.memoryType}</p>
                </div>
                <div>
                  <p className="text-gray-500 uppercase text-xs font-medium">Importance</p>
                  <p className="mt-1">{selectedNodeDetail.importance.toFixed(2)}</p>
                </div>
                {selectedNodeDetail.project && (
                  <div>
                    <p className="text-gray-500 uppercase text-xs font-medium">Project</p>
                    <p className="mt-1">{selectedNodeDetail.project}</p>
                  </div>
                )}
              </div>
            ) : (
              <p className="text-sm text-gray-500">Loading details...</p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
