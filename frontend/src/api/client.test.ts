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

  it('rejects percent-encoded directory traversal', () => {
    expect(() => getValidatedPath('api/%2e%2e%2fsecret')).toThrow('Security Error: Invalid path segments')
    expect(() => getValidatedPath('api/%2E%2E%2Fsecret')).toThrow('Security Error: Invalid path segments')
    expect(() => getValidatedPath('api/%2e%2e/secret')).toThrow('Security Error: Invalid path segments')
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
    vi.useFakeTimers()
    
    // Mock fetch to hang and listen to signal
    vi.mocked(window.fetch).mockImplementation((_url, init?: RequestInit) => {
      return new Promise((_, reject) => {
        if (init?.signal) {
          init.signal.addEventListener('abort', () => {
            const err = new Error('The user aborted a request.')
            err.name = 'AbortError'
            reject(err)
          })
        }
      })
    })

    const promise = apiClient.get('status', { timeout: 100 })
    
    // Fast-forward time
    vi.advanceTimersByTime(150)
    
    await expect(promise).rejects.toThrow('API Request Timeout')
    vi.useRealTimers()
  })

  it('relays external AbortSignal', async () => {
    const controller = new AbortController()

    vi.mocked(window.fetch).mockImplementation((_url, init?: RequestInit) => {
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
      })
    })

    const promise = apiClient.get('status', { signal: controller.signal })
    controller.abort()

    await expect(promise).rejects.toHaveProperty('name', 'AbortError')
  })
})
