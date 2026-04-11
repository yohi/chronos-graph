import { useEffect, useRef, useState } from 'react'
import { useLogStore, LogEntry } from '../stores/logStore'

function LogRow({ entry }: { entry: LogEntry }) {
  const levelColors: Record<string, string> = {
    DEBUG: 'text-gray-500',
    INFO: 'text-blue-500',
    WARNING: 'text-yellow-500',
    ERROR: 'text-red-500',
    CRITICAL: 'text-red-700 font-bold',
  }

  return (
    <div className="flex gap-2 py-1 font-mono text-sm hover:bg-gray-50 dark:hover:bg-gray-700">
      <span className="text-gray-400 w-36 shrink-0">
        {new Date(entry.timestamp).toLocaleTimeString()}
      </span>
      <span className={`w-16 shrink-0 ${levelColors[entry.level] || 'text-gray-500'}`}>
        {entry.level}
      </span>
      <span className="text-gray-600 dark:text-gray-300 truncate">{entry.message}</span>
    </div>
  )
}

export default function LogExplorer() {
  const { logs, isStreaming, error, connect, disconnect } = useLogStore()
  const [filter, setFilter] = useState<string>('ALL')
  const scrollRef = useRef<HTMLDivElement>(null)
  const [autoScroll, setAutoScroll] = useState(true)

  useEffect(() => {
    connect()
    return () => disconnect()
  }, [connect, disconnect])

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = 0
    }
  }, [logs, autoScroll])

  const filteredLogs = filter === 'ALL' ? logs : logs.filter((log) => log.level === filter)

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Log Explorer</h1>
          <p className="text-gray-500 dark:text-gray-400">Real-time log streaming</p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="px-3 py-2 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg"
          >
            <option value="ALL">All Levels</option>
            <option value="DEBUG">DEBUG</option>
            <option value="INFO">INFO</option>
            <option value="WARNING">WARNING</option>
            <option value="ERROR">ERROR</option>
          </select>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={autoScroll}
              onChange={(e) => setAutoScroll(e.target.checked)}
              className="rounded"
            />
            <span className="text-sm text-gray-600 dark:text-gray-400">Auto-scroll</span>
          </label>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 text-red-600 dark:text-red-400">
          {error}
        </div>
      )}

      <div
        ref={scrollRef}
        className="h-[600px] overflow-y-auto bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4"
      >
        {filteredLogs.length === 0 ? (
          <div className="text-center text-gray-500 py-8">
            {isStreaming ? 'Waiting for logs...' : 'Disconnected'}
          </div>
        ) : (
          filteredLogs.map((log, idx) => (
            <LogRow key={`${log.timestamp}-${idx}`} entry={log} />
          ))
        )}
      </div>
    </div>
  )
}