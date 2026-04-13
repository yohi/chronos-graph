import { useEffect, useState } from 'react'

interface Stats {
  node_count: number
  edge_count: number
  memory_count: number
}

export default function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/stats')
      .then((res) => {
        if (!res.ok) throw new Error('Failed to fetch stats')
        return res.json()
      })
      .then((data) => {
        setStats(data)
        setLoading(false)
      })
      .catch((err) => {
        setError(err.message)
        setLoading(false)
      })
  }, [])

  if (loading) return <div className="p-8">Loading dashboard data...</div>
  if (error) return <div className="p-8 text-red-500">Error: {error}</div>

  return (
    <div className="p-8">
      <h2 className="text-2xl font-bold mb-6">System Overview</h2>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <StatsCard title="Nodes" value={stats?.node_count ?? 0} />
        <StatsCard title="Edges" value={stats?.edge_count ?? 0} />
        <StatsCard title="Memories" value={stats?.memory_count ?? 0} />
      </div>
    </div>
  )
}

function StatsCard({ title, value }: { title: string; value: number }) {
  return (
    <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow-sm border border-gray-200 dark:border-gray-700">
      <p className="text-sm text-gray-500 dark:text-gray-400 font-medium uppercase">{title}</p>
      <p className="text-3xl font-bold mt-2">{value.toLocaleString()}</p>
    </div>
  )
}
