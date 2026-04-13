import { useEffect, useState, useRef } from 'react'

interface LogEntry {
  id: string
  timestamp: string
  level: string
  logger: string
  message: string
}

export default function LogExplorer() {
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [status, setStatus] = useState<'connecting' | 'connected' | 'error'>('connecting')
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const isMountedRef = useRef(true)

  useEffect(() => {
    isMountedRef.current = true

    // 過去のログを取得 (最新が上に来るようにソート/リバースを確認)
    fetch('/api/logs/recent?limit=50')
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`)
        return res.json()
      })
      .then((data: unknown) => {
        if (!isMountedRef.current) return
        if (!Array.isArray(data)) {
          console.error('Expected array of logs, got:', typeof data)
          setLogs([])
          return
        }

        // Validate and add unique IDs if missing
        const validLogs: LogEntry[] = data
          .filter((entry: any): entry is LogEntry => (
            entry &&
            typeof entry.timestamp === 'string' &&
            typeof entry.message === 'string' &&
            typeof entry.level === 'string' &&
            typeof entry.logger === 'string'
          ))
          .map((entry, idx) => ({
            ...entry,
            id: entry.id || `${entry.timestamp}-${entry.logger}-${idx}`
          }))

        // 常に最新が先頭になるように並び替える
        const sorted = [...validLogs].sort(
          (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime(),
        )
        setLogs(sorted)
      })
      .catch((err) => {
        console.error('Failed to fetch recent logs:', err)
        if (isMountedRef.current) setLogs([])
      })

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    const wsUrl = `${protocol}//${host}/api/logs/ws`

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
          const entry = JSON.parse(event.data)
          // 厳密なバリデーション: 全ての必須フィールドが文字列であることを確認
          if (
            entry &&
            typeof entry.timestamp === 'string' &&
            typeof entry.message === 'string' &&
            typeof entry.level === 'string' &&
            typeof entry.logger === 'string'
          ) {
            const logEntry: LogEntry = {
              ...entry,
              id: entry.id || `${entry.timestamp}-${entry.logger}-${Math.random()}`
            }
            setLogs((prev) => [logEntry, ...prev].slice(0, 1000))
          } else {
            console.warn('Received invalid log entry format via WS:', entry)
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
