const DEFAULT_BASE_URL = '/api'

/**
 * Valid allowed origins for cross-origin API access (typically development).
 * In production, same-origin is preferred.
 */
const ALLOWED_ORIGINS = [
  'http://localhost:8000',
  'http://127.0.0.1:8000',
  'http://localhost:5173',
  'http://127.0.0.1:5173',
]

/**
 * Validates and normalizes the API base URL.
 * Shared between HTTP client and WebSocket manager.
 */
export function normalizeApiBaseUrl(rawUrl: string | null): string {
  if (!rawUrl || !rawUrl.trim()) return DEFAULT_BASE_URL

  const urlStr = rawUrl.trim()

  // Always allow standard relative /api path
  if (urlStr === '/api' || urlStr === '/api/') return '/api'

  try {
    // Attempt to parse as full URL, defaulting to same origin for relative-looking paths
    const url = new URL(urlStr, window.location.origin)

    // Allow same-origin or explicit whitelist (localhost dev servers)
    const isSameOrigin = url.origin === window.location.origin
    const isWhitelisted = ALLOWED_ORIGINS.includes(url.origin)

    if (isSameOrigin || isWhitelisted) {
      return urlStr
    }
  } catch {
    // Ignore invalid URL formats and fallback
  }

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
