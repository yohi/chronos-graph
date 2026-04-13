import { useEffect } from 'react'
import { useStatsStore } from '../stores/statsStore'
import type { DashboardStats } from '../types/api'

export default function Dashboard() {
  const { summary, loading, error, fetchSummary } = useStatsStore()

  useEffect(() => {
    fetchSummary()
  }, [fetchSummary])

  if (loading) return <div className="p-8">Loading dashboard data...</div>
  if (error) return <div className="p-8 text-red-500">Error: {error}</div>

  return (
    <div className="p-8">
      <h2 className="text-2xl font-bold mb-6">System Overview</h2>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <StatsCard title="Active Memories" value={summary?.activeCount ?? 0} />
        <StatsCard title="Archived Memories" value={summary?.archivedCount ?? 0} />
        <StatsCard title="Total Memories" value={summary?.totalCount ?? 0} />
        <StatsCard title="Graph Edges" value={summary?.edgeCount ?? 0} />
        <StatsCard title="Projects" value={summary?.projectCount ?? 0} />
      </div>
      {summary && <ProjectList summary={summary} />}
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

function ProjectList({ summary }: { summary: DashboardStats }) {
  if (!summary.projects.length) return null
  return (
    <div className="mt-8">
      <h3 className="text-lg font-semibold mb-3">Projects</h3>
      <div className="flex flex-wrap gap-2">
        {summary.projects.map((p) => (
          <span
            key={p}
            className="px-3 py-1 rounded-full text-sm bg-blue-100 dark:bg-blue-900 text-blue-800 dark:text-blue-200"
          >
            {p}
          </span>
        ))}
      </div>
    </div>
  )
}
