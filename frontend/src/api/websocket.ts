/**
 * WebSocket connection manager.
 * Used by useWebSocket hook for log streaming (design doc §5.3).
 */
import { normalizeApiBaseUrl } from './client'

const DEFAULT_WS_BASE = '' // relative — browser resolves ws(s):// automatically

function getWsBase(): string {
  try {
    const stored = localStorage.getItem('chronos-api-base-url')
    const validatedBase = normalizeApiBaseUrl(stored)
    
    if (validatedBase === '/api') {
      return DEFAULT_WS_BASE
    }

    // Convert http(s):// → ws(s)://
    return validatedBase.replace(/^http/, 'ws').replace(/\/api$/, '')
  } catch {
    // localStorage unavailable
  }
  return DEFAULT_WS_BASE
}

export function buildWsUrl(path: string): string {
  const base = getWsBase()
  if (base) return `${base}${path}`
  // Relative WebSocket URL
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${location.host}${path}`
}
