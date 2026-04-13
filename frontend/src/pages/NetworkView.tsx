import { useEffect, useRef, useState } from 'react'
import cytoscape from 'cytoscape'
// @ts-ignore
import coseBilkent from 'cytoscape-cose-bilkent'

cytoscape.use(coseBilkent)

interface GraphNode {
  data: {
    id: string
    label: string
    memoryType: string
    importance: number
    project?: string
  }
}

interface GraphEdge {
  data: {
    id: string
    source: string
    target: string
    edgeType: string
  }
}

interface GraphData {
  elements: {
    nodes: GraphNode[]
    edges: GraphEdge[]
  }
}

export default function NetworkView() {
  const containerRef = useRef<HTMLDivElement>(null)
  const cyRef = useRef<cytoscape.Core | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let isMounted = true

    fetch('/api/graph/layout?limit=100')
      .then((res) => {
        if (!res.ok) throw new Error('Failed to fetch graph data')
        return res.json()
      })
      .then((data: GraphData) => {
        if (!isMounted || !containerRef.current) return

        if (cyRef.current) {
          cyRef.current.destroy()
        }

        cyRef.current = cytoscape({
          container: containerRef.current,
          elements: data.elements,
          style: [
            {
              selector: 'node',
              style: {
                'background-color': '#666',
                'label': 'data(label)',
                'font-size': '10px',
                'text-valign': 'center',
                'text-halign': 'center',
                'color': '#fff',
                'text-outline-width': 1,
                'text-outline-color': '#666',
                'width': 'mapData(importance, 0, 1, 20, 50)',
                'height': 'mapData(importance, 0, 1, 20, 50)',
              },
            },
            {
              selector: 'node[memoryType="episodic"]',
              style: {
                'background-color': '#ef4444',
                'text-outline-color': '#ef4444',
              },
            },
            {
              selector: 'node[memoryType="semantic"]',
              style: {
                'background-color': '#3b82f6',
                'text-outline-color': '#3b82f6',
              },
            },
            {
              selector: 'edge',
              style: {
                'width': 2,
                'line-color': '#ccc',
                'target-arrow-color': '#ccc',
                'target-arrow-shape': 'triangle',
                'curve-style': 'bezier',
                'label': 'data(edgeType)',
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
          } as any,
        })

        setLoading(false)
      })
      .catch((err) => {
        if (isMounted) {
          setError(err.message)
          setLoading(false)
        }
      })

    return () => {
      isMounted = false
      if (cyRef.current) {
        cyRef.current.destroy()
        cyRef.current = null
      }
    }
  }, [])

  return (
    <div className="p-8 h-full flex flex-col">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Network View</h2>
        <div className="text-sm text-gray-500">
          Showing top 100 memories by importance
        </div>
      </div>

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
        <div ref={containerRef} className="w-full h-full" />
      </div>
    </div>
  )
}
