import type { LogEntry } from '../types/api'

type LogLevel = LogEntry['level']

/**
 * Filter implementation used across all actions.
 */
export const applyFilter = (
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

/**
 * Deduplicates and merges log entries based on their content, preserving order (newest last).
 */
export const mergeAndDedupe = (prev: LogEntry[], incoming: LogEntry[]): LogEntry[] => {
  const combined = [...prev, ...incoming]
  const seen = new Set<string>()
  const result: LogEntry[] = []

  // Iterate backwards to keep the latest instance of a duplicate
  for (let i = combined.length - 1; i >= 0; i--) {
    const e = combined[i]
    const key = `${e.timestamp}|${e.logger}|${e.message}`
    if (!seen.has(key)) {
      seen.add(key)
      result.push(e)
    }
  }
  return result.reverse()
}
