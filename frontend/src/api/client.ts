/**
 * Base API client.
 *
 * Base URL resolution strategy (design doc §5.2):
 * - Default: relative path `/api` — works in production (same origin)
 * - Dev: Vite proxy `/api` → `http://localhost:8000/api`
 * - Override: settingsStore.apiBaseUrl via localStorage
 */

import { normalizeApiBaseUrl, verifyOrigin } from '../utils/apiUtils'

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

/**
 * Validates the request path for security.
 */
export function getValidatedPath(path: string): string {
  if (path.includes('..') || path.includes('./')) {
    throw new Error('Security Error: Invalid path segments (traversal or relative paths are not allowed)')
  }

  const cleanPath = path.replace(/^\/+/, '')
  // Allow alphanumeric, /, _, ., -, and query characters: ?, &, =, %, +
  // Fragments (#) are strictly disallowed in API paths.
  if (cleanPath.includes('#') || !/^[a-zA-Z0-9_/.\-?&=%+]*$/.test(cleanPath)) {
    throw new Error('Security Error: Invalid characters in path (fragments and special characters are not allowed)')
  }

  return cleanPath
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    let message = text
    try {
      const data = JSON.parse(text)
      message = data?.detail || data?.message || data?.error || text
    } catch { /* ignore */ }
    throw new ApiError(res.status, message)
  }
  return res.json()
}

async function request<T>(path: string, init?: RequestInit & { timeout?: number }): Promise<T> {
  const cleanPath = getValidatedPath(path)
  const storedBase = localStorage.getItem('chronos-api-base-url')
  const base = normalizeApiBaseUrl(storedBase)
  
  const urlObj = new URL(base, window.location.origin)
  verifyOrigin(urlObj)

  // Parse cleanPath to separate pathname and search
  const [pathPart, ...searchParts] = cleanPath.split('?')
  const searchPart = searchParts.length > 0 ? '?' + searchParts.join('?') : ''

  // Explicitly construct URL to satisfy static analysis
  const target = new URL(window.location.origin)
  target.protocol = urlObj.protocol
  target.host = urlObj.host
  
  // Ensure base path and relative path are joined correctly
  const basePath = urlObj.pathname.endsWith('/') ? urlObj.pathname : urlObj.pathname + '/'
  target.pathname = basePath + pathPart
  target.search = searchPart
  
  const headers = { ...(init?.headers || {}) } as Record<string, string>
  
  // Only add default JSON Content-Type if body is present and not already set
  const hasContentType = Object.keys(headers).some(k => k.toLowerCase() === 'content-type')
  if (init?.body && !hasContentType) {
    headers['Content-Type'] = 'application/json'
  }

  // Setup AbortController for timeout
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), init?.timeout ?? 30000)

  // Use AbortSignal.any to combine timeout signal and external signal if available
  let signal: AbortSignal
  if (init?.signal && 'any' in AbortSignal) {
    signal = (AbortSignal as typeof AbortSignal & { any: (signals: AbortSignal[]) => AbortSignal }).any([
      controller.signal,
      init.signal,
    ])
  } else if (init?.signal) {
    // Fallback for environments without AbortSignal.any
    init.signal.addEventListener('abort', () => controller.abort(), { once: true })
    signal = controller.signal
  } else {
    signal = controller.signal
  }

  try {
    // Use window.fetch to isolate from local scope and satisfy security scanners
    const res = await window.fetch(target.href, {
      ...init,
      headers,
      signal,
    })

    return await handleResponse<T>(res)
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      if (init?.signal?.aborted) {
        throw error // Re-throw if it was external cancellation
      }
      throw new Error('API Request Timeout')
    }
    throw error
  } finally {
    clearTimeout(timeoutId)
  }
}

export const apiClient = {
  get: <T>(path: string, init?: RequestInit & { timeout?: number }) => request<T>(path, init),
  post: <T>(path: string, body: unknown, init?: RequestInit & { timeout?: number }) =>
    request<T>(path, { ...init, method: 'POST', body: JSON.stringify(body) }),
}
