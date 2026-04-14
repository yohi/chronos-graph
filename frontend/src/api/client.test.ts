import { describe, it, expect, vi, beforeEach } from 'vitest'
import { getValidatedPath, apiClient } from './client'

describe('getValidatedPath', () => {
  it('allows valid paths', () => {
    expect(getValidatedPath('api/v1/status')).toBe('api/v1/status')
    expect(getValidatedPath('/api/v1/status')).toBe('api/v1/status')
    expect(getValidatedPath('logs?level=INFO')).toBe('logs?level=INFO')
  })

  it('rejects directory traversal (..)', () => {
    expect(() => getValidatedPath('../etc/passwd')).toThrow('Security Error: Invalid path segments')
    expect(() => getValidatedPath('api/../secret')).toThrow('Security Error: Invalid path segments')
  })

  it('rejects relative path segments (./)', () => {
    expect(() => getValidatedPath('./api')).toThrow('Security Error: Invalid path segments')
    expect(() => getValidatedPath('api/./status')).toThrow('Security Error: Invalid path segments')
  })

  it('rejects fragments (#)', () => {
    expect(() => getValidatedPath('api/status#fragment')).toThrow('Security Error: Invalid characters in path')
  })

  it('rejects disallowed special characters', () => {
    expect(() => getValidatedPath('api/status;rm')).toThrow('Security Error: Invalid characters in path')
    expect(() => getValidatedPath('api/status$SHELL')).toThrow('Security Error: Invalid characters in path')
  })
})

describe('apiClient timeout and signals', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
    vi.stubGlobal('window', {
      fetch: vi.fn(),
      location: { origin: 'http://localhost:3000' }
    })
    vi.stubGlobal('location', { origin: 'http://localhost:3000' })
    vi.stubGlobal('localStorage', {
      getItem: vi.fn().mockReturnValue(null),
    })
  })

  it('throws "API Request Timeout" on timeout', async () => {
    // Mock fetch to hang
    vi.mocked(window.fetch).mockImplementation(() => new Promise(() => {}))
    
    // We use a shorter timeout for testing if possible, but here we'll mock the AbortError
    vi.mocked(window.fetch).mockRejectedValueOnce(Object.assign(new Error('The user aborted a request.'), { name: 'AbortError' }))

    const promise = apiClient.get('status')
    await expect(promise).rejects.toThrow('API Request Timeout')
  })

  it('relays external AbortSignal', async () => {
    const controller = new AbortController()

    vi.mocked(window.fetch).mockImplementation((_url, init: any) => {
      const signal = init?.signal
      return new Promise((resolve, reject) => {
        if (signal?.aborted) {
          const err = new Error('Aborted')
          err.name = 'AbortError'
          return reject(err)
        }
        if (signal) {
          signal.addEventListener('abort', () => {
            const err = new Error('Aborted')
            err.name = 'AbortError'
            reject(err)
          })
        }
        // If not aborted, just hang (or resolve if we want to test success)
      })
    })

    const promise = apiClient.get('status', { signal: controller.signal } as any)
    controller.abort()

    await expect(promise).rejects.toHaveProperty('name', 'AbortError')
  })
})
