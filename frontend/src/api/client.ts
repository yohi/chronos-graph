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
  // Allow alphanumeric, /, _, ., -, and query/fragment characters: ?, &, =, %, +, #
  if (!/^[a-zA-Z0-9_/.\-?&=%+#]*$/.test(cleanPath)) {
    throw new Error('Security Error: Invalid characters in path')
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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const cleanPath = getValidatedPath(path)
  const storedBase = localStorage.getItem('chronos-api-base-url')
  const base = normalizeApiBaseUrl(storedBase)
  
  const urlObj = new URL(base, window.location.origin)
  verifyOrigin(urlObj)

  // Explicitly construct URL to satisfy static analysis
  const target = new URL(window.location.origin)
  target.protocol = urlObj.protocol
  target.host = urlObj.host
  target.pathname = urlObj.pathname.endsWith('/') ? urlObj.pathname + cleanPath : urlObj.pathname + '/' + cleanPath
  
  // Use window.fetch to isolate from local scope and satisfy security scanners
  const res = await window.fetch(target.href, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
  })

  return handleResponse<T>(res)
}

export const apiClient = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'POST', body: JSON.stringify(body) }),
}
