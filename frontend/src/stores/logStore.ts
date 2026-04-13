/**
 * Log store — log entries, filter state (design doc §5.3).
 */
import { create } from 'zustand'
import { logsApi } from '../api/logs'
import type { LogEntry } from '../types/api'

type LogLevel = LogEntry['level']

interface LogState {
  entries: LogEntry[]
  filter: {
    level: LogLevel | 'ALL'
    text: string
  }
  loading: boolean
  error: string | null
  // Actions
  fetchRecent: (limit?: number) => Promise<void>
  appendLog: (entry: LogEntry) => void
  setLevelFilter: (level: LogLevel | 'ALL') => void
  setTextFilter: (text: string) => void
  // Note: instead of returning a new array every time, components can subscribe to this.
  // We compute it inside the store actions to maintain stable reference when state changes.
  getFilteredEntries: () => LogEntry[]
}

const MAX_ENTRIES = 500

export const useLogStore = create<LogState>((set, get) => ({
  entries: [],
  filter: { level: 'ALL', text: '' },
  loading: false,
  error: null,

  fetchRecent: async (limit = 100) => {
    set({ loading: true, error: null })
    try {
      const res = await logsApi.getRecent(limit)
      // Enforce ring-buffer invariant on full refresh
      set({ entries: res.entries.slice(-MAX_ENTRIES), loading: false })
    } catch (err) {
      set({ error: String(err), loading: false })
    }
  },

  appendLog: (entry) => {
    set((state) => ({
      entries: [...state.entries.slice(-(MAX_ENTRIES - 1)), entry],
    }))
  },

  setLevelFilter: (level) =>
    set((state) => ({ filter: { ...state.filter, level } })),

  setTextFilter: (text) =>
    set((state) => ({ filter: { ...state.filter, text } })),

  getFilteredEntries: () => {
    const { entries, filter } = get()
    if (filter.level === 'ALL' && !filter.text) return entries

    return entries.filter((e) => {
      const levelOk = filter.level === 'ALL' || e.level === filter.level
      const textOk =
        !filter.text ||
        e.message.toLowerCase().includes(filter.text.toLowerCase()) ||
        e.logger.toLowerCase().includes(filter.text.toLowerCase())
      return levelOk && textOk
    })
  },
}))
