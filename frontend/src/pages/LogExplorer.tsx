import { useEffect, useState, useRef } from 'react'

interface LogEntry {
  timestamp: string
  level: string
  logger: string
  message: string
}

export default function LogExplorer() {
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [status, setStatus] = useState<'connecting' | 'connected' | 'error'>('connecting')
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    // 過去のログを取得
    fetch('/api/logs/recent?limit=50')
      .then((res) => res.json())
      .then((data) => {
        setLogs(data)
      })
      .catch((err) => {
        console.error('Failed to fetch recent logs:', err)
      })

    // WebSocket 接続
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    const wsUrl = `${protocol}//${host}/api/logs/ws`
    
    const connect = () => {
      const socket = new WebSocket(wsUrl)
      wsRef.current = socket

      socket.onopen = () => {
        setStatus('connected')
      }
      socket.onmessage = (event) => {
        const entry: LogEntry = JSON.parse(event.data)
        setLogs((prev) => [entry, ...prev].slice(0, 1000))
      }
      socket.onclose = () => {
        setStatus('error')
        setTimeout(connect, 3000) // 3秒後に再接続
      }
      socket.onerror = () => {
        setStatus('error')
      }
    }

    connect()

    return () => {
      wsRef.current?.close()
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
          logs.map((log, i) => (
            <div key={i} className="mb-1">
              <span className="text-gray-500">[{log.timestamp.split('T')[1].split('.')[0]}]</span>{' '}
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
