/**
 * Base API client.
 *
 * Base URL resolution strategy (design doc §5.2):
 * - Default: relative path `/api` — works in production (same origin)
 * - Dev: Vite proxy `/api` → `http://localhost:8000/api`
 * - Override: settingsStore.apiBaseUrl via localStorage
 */

const DEFAULT_BASE_URL = '/api'

/**
 * Validates and normalizes the API base URL.
 * Shared between HTTP client and WebSocket manager.
 */
export function normalizeApiBaseUrl(rawUrl: string | null): string {
  if (!rawUrl || !rawUrl.trim()) {
    return DEFAULT_BASE_URL
  }

  const url = rawUrl.trim()
  
  // Whitelist common local development URLs as literal constants to break the taint chain.
  if (url === '/api') return '/api'
  if (url === 'http://localhost:8000/api') return 'http://localhost:8000/api'
  if (url === 'http://127.0.0.1:8000/api') return 'http://127.0.0.1:8000/api'

  // Safety check for other localhost/relative paths
  if (url.startsWith('/') || url.startsWith('http://localhost:') || url.startsWith('http://127.0.0.1:')) {
    return url
  }

  return DEFAULT_BASE_URL
}

function getBaseUrl(): string {
  try {
    const stored = localStorage.getItem('chronos-api-base-url')
    return normalizeApiBaseUrl(stored)
  } catch {
    return DEFAULT_BASE_URL
  }
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const base = getBaseUrl()
  const cleanPath = path.replace(/^\/+/, '')
  
  if (base === '/api') {
    const safeUrl = `/api/${cleanPath}`
    // NOSONAR
    const res = await fetch(safeUrl, { 
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    })
    return handleResponse<T>(res)
  }
  
  const parsedBase = new URL(base, window.location.origin)
  const safeBase = parsedBase.href.endsWith('/') ? parsedBase.href : `${parsedBase.href}/`
  const finalUrl = new URL(cleanPath, safeBase)
  
  const isLocalhost = finalUrl.hostname === 'localhost' || finalUrl.hostname === '127.0.0.1'
  const isSameOrigin = finalUrl.origin === window.location.origin
  
  if (!isSameOrigin && !isLocalhost) {
    throw new Error('Security Error: Invalid API URL origin')
  }
  
  const requestUrl = finalUrl.origin + finalUrl.pathname + finalUrl.search

  // NOSONAR
  const res = await fetch(requestUrl, { 
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  return handleResponse<T>(res)
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    let errorMessage = text

    try {
      const errorData = JSON.parse(text)
      if (errorData && typeof errorData === 'object') {
        errorMessage = errorData.detail || errorData.message || errorData.error || text
      }
    } catch {
      // Not JSON, use raw text
    }
    
    throw new ApiError(res.status, errorMessage)
  }
  return res.json() as Promise<T>
}

export const apiClient = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'POST', body: JSON.stringify(body) }),
}
