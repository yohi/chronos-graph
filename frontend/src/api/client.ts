/**
 * Base API client.
 *
 * Base URL resolution strategy (design doc §5.2):
 * - Default: relative path `/api` — works in production (same origin)
 * - Dev: Vite proxy `/api` → `http://localhost:8000/api`
 * - Override: settingsStore.apiBaseUrl via localStorage
 */

const DEFAULT_BASE_URL = '/api'

function getBaseUrl(): string {
  try {
    const stored = localStorage.getItem('chronos-api-base-url')
    if (stored && stored.trim()) {
      const url = stored.trim()
      // Prevent SSRF: only allow relative paths or local development URLs
      if (url.startsWith('/') || url.startsWith('http://localhost:') || url.startsWith('http://127.0.0.1:')) {
        return url
      }
    }
  } catch {
    // localStorage unavailable
  }
  return DEFAULT_BASE_URL
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
  
  // Construct a safe absolute URL using the URL API
  // window.location.origin is used as the base for relative URLs
  const baseUrl = new URL(base, window.location.origin)
  
  // Clean path to prevent URL segment replacement or protocol-relative URLs
  // For example, if path is '/memories', and baseUrl is 'http://localhost/api/',
  // new URL('/memories', ...) replaces the path with '/memories' instead of '/api/memories'.
  // By removing the leading slash, it appends properly to the base path.
  const cleanPath = path.replace(/^\/+/, '')
  const safeBase = baseUrl.href.endsWith('/') ? baseUrl.href : `${baseUrl.href}/`
  
  const finalUrl = new URL(cleanPath, safeBase)
  
  // Final validation to ensure the constructed URL points to a trusted origin.
  // We use strict equality for hostname/origin check to prevent bypasses like 'localhost.evil.com'.
  const isLocalhost = finalUrl.hostname === 'localhost' || finalUrl.hostname === '127.0.0.1'
  const isSameOrigin = finalUrl.origin === window.location.origin
  
  if (!isSameOrigin && !isLocalhost) {
    throw new Error('Security Error: Invalid API URL origin')
  }
  
  // We use // NOSONAR to suppress the static analysis warning (SSRF/S5144).
  // The URL has been strictly validated against trusted origins above.
  const res = await fetch(finalUrl.href, { // NOSONAR
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  })
  if (!res.ok) {
    let errorMessage = res.statusText
    try {
      const errorData = await res.json()
      if (errorData && typeof errorData === 'object') {
        errorMessage = errorData.detail || errorData.message || errorData.error || JSON.stringify(errorData)
      }
    } catch {
      // Not a JSON response, fallback to status text or text body
      const text = await res.text().catch(() => '')
      if (text) {
        errorMessage = text
      }
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
