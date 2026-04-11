import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useStatsStore } from '../src/stores/statsStore'

describe('statsStore', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useStatsStore.setState({ stats: null, isLoading: false, error: null })
  })

  it('should fetch stats successfully', async () => {
    const mockStats = {
      activeCount: 100,
      archivedCount: 20,
      totalCount: 120,
      edgeCount: 300,
      projectCount: 5,
      projects: ['proj-a', 'proj-b'],
    }

    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockStats),
    })
    vi.stubGlobal('fetch', mockFetch)

    const store = useStatsStore.getState()
    await store.fetchStats()

    expect(mockFetch).toHaveBeenCalledWith('/api/stats/summary')
    const state = useStatsStore.getState()
    expect(state.stats).toEqual(mockStats)
    expect(state.isLoading).toBe(false)
  })

  it('should handle fetch error', async () => {
    const mockFetch = vi.fn().mockRejectedValue(new Error('Network error'))
    vi.stubGlobal('fetch', mockFetch)

    const store = useStatsStore.getState()
    await store.fetchStats()

    const state = useStatsStore.getState()
    expect(state.error).toBe('Network error')
    expect(state.isLoading).toBe(false)
  })
})