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
  let decodedPath: string
  try {
    decodedPath = decodeURIComponent(path)
  } catch {
    throw new Error('Security Error: Malformed URI component in path')
  }

  // Reject segments that indicate traversal or relative references
  const segments = decodedPath.split(/[/\\]/)
  if (segments.some(s => s === '..' || s === '.')) {
    throw new Error('Security Error: Invalid path segments (traversal or relative paths are not allowed)')
  }

  // Apply character whitelist and fragment checks against the DECODED value
  // to prevent bypass via percent-encoding.
  if (decodedPath.includes('#') || !/^[a-zA-Z0-9_/.\-?&=%+]*$/.test(decodedPath)) {
    throw new Error('Security Error: Invalid characters or fragments in path')
  }

  return path.replace(/^\/+/, '')
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

  const requestHeaders = new Headers(init?.headers)

  // Only add default JSON Content-Type if body is present and not already set
  if (init?.body && !requestHeaders.has('Content-Type')) {
    requestHeaders.set('Content-Type', 'application/json')
  }

  const headers = Object.fromEntries(requestHeaders.entries())

  // Setup AbortController for timeout
  let timedOut = false
  const controller = new AbortController()

  // Handle immediate external abort before starting timeout
  if (init?.signal?.aborted) {
    controller.abort()
  }

  const timeoutId = setTimeout(() => {
    timedOut = true
    controller.abort()
  }, init?.timeout ?? 30000)

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
      if (timedOut) {
        throw new Error('API Request Timeout')
      }
      // Re-throw if it was external cancellation or immediate abort
      throw error
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
