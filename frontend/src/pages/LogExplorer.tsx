import { useEffect, useState, useRef } from 'react'
import { logsApi } from '../api/logs'
import { buildWsUrl } from '../api/websocket'
import type { LogEntry } from '../types/api'

interface DisplayLogEntry extends LogEntry {
  id: string
}

// Helper to generate a deterministic ID for a log entry to enable deduplication
const getLogId = (entry: LogEntry): string => {
  return `${entry.timestamp}|${entry.level}|${entry.logger}|${entry.message}`
}

type Severity = LogEntry['level'] | 'ALL'
const SEVERITY_LEVELS: Severity[] = ['ALL', 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']

const LEVEL_COLORS: Record<LogEntry['level'], string> = {
  DEBUG: 'text-gray-400',
  INFO: 'text-blue-400',
  WARNING: 'text-yellow-400',
  ERROR: 'text-red-400',
  CRITICAL: 'text-red-500',
}

export default function LogExplorer() {
  const [logs, setLogs] = useState<DisplayLogEntry[]>([])
  const [status, setStatus] = useState<'connecting' | 'connected' | 'error'>('connecting')
  const [severityFilter, setSeverityFilter] = useState<Severity>('ALL')
  const [textFilter, setTextFilter] = useState('')
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const isMountedRef = useRef(true)

  useEffect(() => {
    isMountedRef.current = true

    // Fetch past logs via logsApi (which uses apiClient and respects localStorage override)
    logsApi.getRecent(50)
      .then((data) => {
        if (!isMountedRef.current) return

        // Validate and add deterministic IDs for React keys and deduplication
        const fetchedLogs: DisplayLogEntry[] = data.entries
          .map((entry) => ({
            ...entry,
            id: getLogId(entry)
          }))

        // Merge with existing logs (e.g. from WS received during fetch)
        setLogs((prev) => {
          const merged = [...prev, ...fetchedLogs]
          // Deduplicate by ID
          const uniqueMap = new Map<string, DisplayLogEntry>()
          merged.forEach((item) => uniqueMap.set(item.id, item))
          const unique = Array.from(uniqueMap.values())

          // Sort descending (latest first)
          return unique.sort(
            (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime(),
          ).slice(0, 1000)
        })
      })
      .catch((err) => {
        console.error('Failed to fetch recent logs:', err)
        // Keep existing logs (might have WS data)
      })

    // Use buildWsUrl to respect localStorage override
    const wsUrl = buildWsUrl('/api/logs/ws')

    const connect = () => {
      if (!isMountedRef.current) return

      setStatus('connecting')
      const socket = new WebSocket(wsUrl)
      wsRef.current = socket

      socket.onopen = () => {
        if (isMountedRef.current) {
          setStatus('connected')
        }
      }

      socket.onmessage = (event) => {
        if (!isMountedRef.current) return
        try {
          const parsed = JSON.parse(event.data)

          // Validation: Perform strict runtime checks (design doc §5.3)
          const isValid = (
            parsed &&
            typeof parsed.timestamp === 'string' &&
            typeof parsed.message === 'string' &&
            ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'].includes(parsed.level) &&
            typeof (parsed.logger ?? '') === 'string'
          )

          if (isValid) {
            const entry: LogEntry = {
              timestamp: parsed.timestamp,
              level: parsed.level as LogEntry['level'],
              message: parsed.message,
              logger: parsed.logger ?? 'unknown'
            }
            const logEntry: DisplayLogEntry = {
              ...entry,
              id: getLogId(entry)
            }
            // Use functional update to merge and deduplicate even for WS messages
            setLogs((prev) => {
              // Quick check if already present
              if (prev.some(l => l.id === logEntry.id)) return prev

              const merged = [logEntry, ...prev]
              return merged.slice(0, 1000)
            })
          } else {
            console.warn('Dropped invalid log entry from WebSocket:', parsed)
          }
        } catch (err) {
          console.warn('Failed to parse WebSocket message:', err)
        }
      }

      socket.onclose = () => {
        if (isMountedRef.current) {
          setStatus('error')
          reconnectTimerRef.current = setTimeout(() => {
            if (isMountedRef.current) {
              setStatus('connecting')
              connect()
            }
          }, 3000)
        }
      }

      socket.onerror = () => {
        if (isMountedRef.current) {
          setStatus('error')
        }
      }
    }

    connect()

    return () => {
      isMountedRef.current = false
      if (wsRef.current) {
        wsRef.current.close()
      }
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current)
      }
    }
  }, [])

  const filteredLogs = logs.filter((log) => {
    if (severityFilter !== 'ALL' && log.level !== severityFilter) return false
    if (textFilter && !log.message.toLowerCase().includes(textFilter.toLowerCase())) return false
    return true
  })

  return (
    <div className="p-8 h-full flex flex-col">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Log Explorer</h2>
        <div className="flex items-center space-x-2 text-sm">
          <span className={`w-2 h-2 rounded-full ${
            status === 'connected' ? 'bg-green-500' : status === 'connecting' ? 'bg-yellow-500' : 'bg-red-500'
          }`} />
          <span className="capitalize">{status}</span>
        </div>
      </div>

      <div className="flex items-center gap-3 mb-4" data-testid="log-filters">
        <div className="flex items-center gap-1">
          {SEVERITY_LEVELS.map((level) => (
            <button
              key={level}
              onClick={() => setSeverityFilter(level)}
              data-testid={`severity-filter-${level.toLowerCase()}`}
              className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                severityFilter === level
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
              }`}
            >
              {level}
            </button>
          ))}
        </div>
        <input
          type="text"
          placeholder="Filter by message..."
          value={textFilter}
          onChange={(e) => setTextFilter(e.target.value)}
          data-testid="log-text-filter"
          className="flex-1 px-3 py-1 text-sm rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      <div className="flex-1 bg-gray-900 text-gray-100 rounded-lg overflow-auto font-mono text-sm p-4">
        {filteredLogs.length === 0 ? (
          <p className="text-gray-500 italic">
            {logs.length === 0 ? 'Waiting for logs...' : 'No logs match the current filter.'}
          </p>
        ) : (
          filteredLogs.map((log) => (
            <div key={log.id} className="mb-1" data-testid="log-entry">
              <span className="text-gray-500">[{log.timestamp.includes('T') ? log.timestamp.split('T')[1].split('.')[0] : log.timestamp}]</span>{' '}
              <span className={`font-bold ${LEVEL_COLORS[log.level]}`}>{log.level.padEnd(8)}</span>{' '}
              <span className="text-gray-400">[{log.logger}]</span>{' '}
              <span>{log.message}</span>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
