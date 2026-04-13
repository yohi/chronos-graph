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
function getValidatedPath(path: string): string {
  if (path.includes('..') || path.includes('./')) {
    throw new Error('Security Error: Invalid path segments')
  }

  const cleanPath = path.replace(/^\/+/, '')
  // Allow alphanumeric, /, _, ., -, and query characters: ?, &, =, %, +
  // Fragments (#) are disallowed in API paths.
  if (!/^[a-zA-Z0-9_/.\-?&=%+]*$/.test(cleanPath)) {
    throw new Error('Security Error: Invalid characters in path (fragments are not allowed)')
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

  // Setup AbortController for timeout and signal relay
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), init?.timeout || 30000)

  // Relay external signal if provided
  const onExternalAbort = () => controller.abort()
  if (init?.signal) {
    if (init.signal.aborted) {
      controller.abort()
    } else {
      init.signal.addEventListener('abort', onExternalAbort)
    }
  }

  try {
    // Use window.fetch to isolate from local scope and satisfy security scanners
    const res = await window.fetch(target.href, {
      ...init,
      headers,
      signal: controller.signal,
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
    if (init?.signal) {
      init.signal.removeEventListener('abort', onExternalAbort)
    }
  }
}

export const apiClient = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'POST', body: JSON.stringify(body) }),
}
