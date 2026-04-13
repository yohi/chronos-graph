import { describe, it, expect, beforeEach } from 'vitest'
import { useLogStore } from './logStore'
import type { LogEntry } from '../types/api'

describe('useLogStore', () => {
  beforeEach(() => {
    // Reset the store state before each test
    useLogStore.setState({
      entries: [],
      filteredEntries: [],
      filter: { level: 'ALL', text: '' },
      loading: false,
      error: null,
      lastFetchId: 0,
    })
  })

  const createMockLog = (level: LogEntry['level'], message: string, logger = 'test-logger'): LogEntry => ({
    timestamp: new Date().toISOString(),
    level,
    message,
    logger,
  })

  it('appends log entries correctly', () => {
    const store = useLogStore.getState()
    store.appendLog(createMockLog('INFO', 'First log'))
    store.appendLog(createMockLog('ERROR', 'Second log'))

    const newStore = useLogStore.getState()
    expect(newStore.entries).toHaveLength(2)
    expect(newStore.entries[0].message).toBe('First log')
    expect(newStore.entries[1].message).toBe('Second log')
  })

  it('enforces a maximum of 500 entries (MAX_ENTRIES)', () => {
    // Add 505 logs
    for (let i = 0; i < 505; i++) {
      useLogStore.getState().appendLog(createMockLog('INFO', `Log ${i}`))
    }

    const newStore = useLogStore.getState()
    expect(newStore.entries).toHaveLength(500)
    // The first 5 logs (0 to 4) should be sliced off
    expect(newStore.entries[0].message).toBe('Log 5')
    expect(newStore.entries[499].message).toBe('Log 504')
  })

  it('filters entries by log level', () => {
    const store = useLogStore.getState()
    store.appendLog(createMockLog('INFO', 'Info log'))
    store.appendLog(createMockLog('ERROR', 'Error log'))
    store.appendLog(createMockLog('WARNING', 'Warning log'))
    store.appendLog(createMockLog('ERROR', 'Another error'))

    store.setLevelFilter('ERROR')
    
    const filtered = useLogStore.getState().filteredEntries
    expect(filtered).toHaveLength(2)
    expect(filtered[0].message).toBe('Error log')
    expect(filtered[1].message).toBe('Another error')
  })

  it('filters entries by text matching message or logger (case-insensitive)', () => {
    const store = useLogStore.getState()
    store.appendLog(createMockLog('INFO', 'Connection established', 'network'))
    store.appendLog(createMockLog('ERROR', 'Timeout occurred', 'system'))
    store.appendLog(createMockLog('INFO', 'Checking system status', 'monitor'))

    // Filter by message
    store.setTextFilter('time')
    let filtered = useLogStore.getState().filteredEntries
    expect(filtered).toHaveLength(1)
    expect(filtered[0].message).toBe('Timeout occurred')

    // Filter by logger
    store.setTextFilter('NET')
    filtered = useLogStore.getState().filteredEntries
    expect(filtered).toHaveLength(1)
    expect(filtered[0].logger).toBe('network')
  })

  it('combines level and text filters correctly', () => {
    const store = useLogStore.getState()
    store.appendLog(createMockLog('INFO', 'Database sync complete', 'db'))
    store.appendLog(createMockLog('ERROR', 'Database connection failed', 'db'))
    store.appendLog(createMockLog('ERROR', 'Network connection failed', 'net'))

    store.setLevelFilter('ERROR')
    store.setTextFilter('database')
    
    const filtered = useLogStore.getState().filteredEntries
    expect(filtered).toHaveLength(1)
    expect(filtered[0].message).toBe('Database connection failed')
  })
})
