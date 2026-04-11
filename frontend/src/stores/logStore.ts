import { create } from 'zustand'

export interface LogEntry {
  timestamp: string
  level: string
  logger: string
  message: string
}

interface LogState {
  logs: LogEntry[]
  isStreaming: boolean
  error: string | null
  connect: () => void
  disconnect: () => void
}

export const useLogStore = create<LogState>((set, get) => {
  let ws: WebSocket | null = null

  return {
    logs: [],
    isStreaming: false,
    error: null,
    connect: () => {
      const { isStreaming } = get()
      if (isStreaming) return

      ws = new WebSocket(`ws://${window.location.host}/ws/logs`)

      ws.onopen = () => {
        set({ isStreaming: true, error: null })
      }

      ws.onmessage = (event) => {
        try {
          const entry = JSON.parse(event.data)
          set((state) => ({
            logs: [entry, ...state.logs].slice(0, 1000),
          }))
        } catch {
          console.error('Failed to parse log entry')
        }
      }

      ws.onerror = () => {
        set({ error: 'WebSocket connection error' })
      }

      ws.onclose = () => {
        set({ isStreaming: false })
      }
    },
    disconnect: () => {
      if (ws) {
        ws.close()
        ws = null
      }
      set({ isStreaming: false })
    },
  }
})