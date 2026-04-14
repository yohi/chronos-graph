import { useEffect, useState, useRef } from 'react'
import { logsApi } from '../api/logs'
import { buildWsUrl } from '../api/websocket'
import type { LogEntry } from '../types/api'

interface DisplayLogEntry extends LogEntry {
  id: string
}

export default function LogExplorer() {
  const [logs, setLogs] = useState<DisplayLogEntry[]>([])
  const [status, setStatus] = useState<'connecting' | 'connected' | 'error'>('connecting')
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const isMountedRef = useRef(true)

  useEffect(() => {
    isMountedRef.current = true

    // Fetch past logs via logsApi (which uses apiClient and respects localStorage override)
    logsApi.getRecent(50)
      .then((data) => {
        if (!isMountedRef.current) return
        
        // Validate and add unique IDs for React keys
        const validLogs: DisplayLogEntry[] = data.entries
          .map((entry, idx) => ({
            ...entry,
            id: `${entry.timestamp}-${entry.logger}-${idx}`
          }))

        // Sort descending (latest first)
        const sorted = [...validLogs].sort(
          (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime(),
        )
        setLogs(sorted)
      })
      .catch((err) => {
        console.error('Failed to fetch recent logs:', err)
        if (isMountedRef.current) setLogs([])
      })

    // Use buildWsUrl to respect localStorage override
    const wsUrl = buildWsUrl('/api/logs/ws')

    const connect = () => {
      if (!isMountedRef.current) return

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
          const entry = JSON.parse(event.data) as LogEntry
          // Validation: Ensure required fields are present
          if (entry && entry.timestamp && entry.message && entry.level) {
            const logEntry: DisplayLogEntry = {
              ...entry,
              id: crypto.randomUUID()
            }
            setLogs((prev) => [logEntry, ...prev].slice(0, 1000))
          }
        } catch (err) {
          console.warn('Failed to parse WebSocket message:', err)
        }
      }

      socket.onclose = () => {
        if (isMountedRef.current) {
          setStatus('error')
          reconnectTimerRef.current = setTimeout(connect, 3000)
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

      <div className="flex-1 bg-gray-900 text-gray-100 rounded-lg overflow-auto font-mono text-sm p-4">
        {logs.length === 0 ? (
          <p className="text-gray-500 italic">Waiting for logs...</p>
        ) : (
          logs.map((log) => (
            <div key={log.id} className="mb-1">
              <span className="text-gray-500">[{log.timestamp.includes('T') ? log.timestamp.split('T')[1].split('.')[0] : log.timestamp}]</span>{' '}
              <span className={`font-bold ${
                log.level === 'ERROR' || log.level === 'CRITICAL' ? 'text-red-400' :
                log.level === 'WARNING' ? 'text-yellow-400' : 'text-blue-400'
              }`}>{log.level.padEnd(8)}</span>{' '}
              <span className="text-gray-400">[{log.logger}]</span>{' '}
              <span>{log.message}</span>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
