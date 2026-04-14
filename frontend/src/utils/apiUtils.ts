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
 * SSRF Protection: Ensures the URL is either a relative path starting with /
 * or a valid absolute URL using the http/https protocols.
 */
export function normalizeApiBaseUrl(rawUrl: string | null): string {
  if (!rawUrl || !rawUrl.trim()) return DEFAULT_BASE_URL

  const urlStr = rawUrl.trim()

  // 1. Valid relative path starting with /
  if (urlStr.startsWith('/') && !urlStr.startsWith('//')) {
    // Basic path traversal check
    if (urlStr.includes('..')) return DEFAULT_BASE_URL
    return urlStr
  }

  try {
    // 2. Absolute URL validation
    const url = new URL(urlStr)

    // SSRF: Restrict to http/https protocols
    if (url.protocol !== 'http:' && url.protocol !== 'https:') {
      return DEFAULT_BASE_URL
    }

    // SSRF: Allow same-origin or explicit whitelist (localhost dev servers)
    // window.location.origin is used as the baseline for 'same-origin'
    const isSameOrigin = url.origin === window.location.origin
    const isWhitelisted = ALLOWED_ORIGINS.includes(url.origin)

    if (isSameOrigin || isWhitelisted) {
      return url.origin + url.pathname.replace(/\/+$/, '')
    }
  } catch {
    // Not a valid absolute URL, and already checked for relative path starting with /
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
