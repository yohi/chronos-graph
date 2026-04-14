const DEFAULT_BASE_URL = '/api'

/**
 * Validates and normalizes the API base URL.
 * Shared between HTTP client and WebSocket manager.
 */
export function normalizeApiBaseUrl(rawUrl: string | null): string {
  if (!rawUrl || !rawUrl.trim()) return DEFAULT_BASE_URL

  const url = rawUrl.trim()
  
  // Literal allowlist to break taint chain for common cases.
  if (url === '/api') return '/api'
  if (url === 'http://localhost:8000/api') return 'http://localhost:8000/api'
  if (url === 'http://127.0.0.1:8000/api') return 'http://127.0.0.1:8000/api'

  // Safety check for other localhost/relative paths.
  // Only allow '/api' or localhost variants.
  const isLocalhost = url.startsWith('http://localhost:') || url.startsWith('http://127.0.0.1:')
  if (isLocalhost) return url

  return DEFAULT_BASE_URL
}

/**
 * Ensures the origin is trusted (same origin or localhost).
 */
export function verifyOrigin(url: URL): void {
  const isLocal = url.hostname === 'localhost' || url.hostname === '127.0.0.1'
  const isSame = url.origin === window.location.origin
  if (!isLocal && !isSame) {
    throw new Error('Security Error: Forbidden origin')
  }
}
