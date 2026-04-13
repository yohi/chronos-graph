/**
 * Log store — log entries, filter state (design doc §5.3).
 */
import { create } from 'zustand'
import { logsApi } from '../api/logs'
import type { LogEntry } from '../types/api'

type LogLevel = LogEntry['level']

interface LogState {
  entries: LogEntry[]
  filteredEntries: LogEntry[] // Pre-calculated filtered result
  filter: {
    level: LogLevel | 'ALL'
    text: string
  }
  loading: boolean
  error: string | null
  lastFetchId: number // To prevent out-of-order async responses
  // Actions
  fetchRecent: (limit?: number) => Promise<void>
  appendLog: (entry: LogEntry) => void
  setLevelFilter: (level: LogLevel | 'ALL') => void
  setTextFilter: (text: string) => void
}

const MAX_ENTRIES = 500

/**
 * Filter implementation used across all actions.
 */
const applyFilter = (
  entries: LogEntry[],
  filter: { level: LogLevel | 'ALL'; text: string }
): LogEntry[] => {
  if (filter.level === 'ALL' && !filter.text) return entries

  const query = filter.text.toLowerCase()
  return entries.filter((e) => {
    const levelOk = filter.level === 'ALL' || e.level === filter.level
    if (!levelOk) return false

    if (!query) return true

    return (
      e.message.toLowerCase().includes(query) ||
      e.logger.toLowerCase().includes(query)
    )
  })
}

export const useLogStore = create<LogState>((set, get) => ({
  entries: [],
  filteredEntries: [],
  filter: { level: 'ALL', text: '' },
  loading: false,
  error: null,
  lastFetchId: 0,

  fetchRecent: async (limit = 100) => {
    const fetchId = get().lastFetchId + 1
    set({ loading: true, error: null, lastFetchId: fetchId })

    try {
      const res = await logsApi.getRecent(limit)
      
      // Guard: only apply if this is still the latest request
      if (get().lastFetchId !== fetchId) return

      const entries = res.entries.slice(-MAX_ENTRIES)
      set((state) => ({
        entries,
        filteredEntries: applyFilter(entries, state.filter),
        loading: false,
      }))
    } catch (err) {
      if (get().lastFetchId !== fetchId) return
      set({ error: String(err), loading: false })
    }
  },

  appendLog: (entry) => {
    set((state) => {
      const newEntries = [...state.entries.slice(-(MAX_ENTRIES - 1)), entry]
      return {
        entries: newEntries,
        filteredEntries: applyFilter(newEntries, state.filter),
      }
    })
  },

  setLevelFilter: (level) =>
    set((state) => {
      const filter = { ...state.filter, level }
      return {
        filter,
        filteredEntries: applyFilter(state.entries, filter),
      }
    }),

  setTextFilter: (text) =>
    set((state) => {
      const filter = { ...state.filter, text }
      return {
        filter,
        filteredEntries: applyFilter(state.entries, filter),
      }
    }),
}))
