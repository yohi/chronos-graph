import { create } from 'zustand'

export interface SystemConfig {
  storageBackend: string
  graphBackend: string
  cacheBackend: string
  embeddingProvider: string
  embeddingModel: string
  logLevel: string
  dashboardPort: number
}

interface SettingsState {
  config: SystemConfig | null
  isLoading: boolean
  error: string | null
  theme: 'light' | 'dark'
  fetchConfig: () => Promise<void>
  setTheme: (theme: 'light' | 'dark') => void
  toggleTheme: () => void
}

export const useSettingsStore = create<SettingsState>((set, get) => ({
  config: null,
  isLoading: false,
  error: null,
  theme: (() => {
    if (typeof window !== 'undefined') {
      return (localStorage.getItem('theme') as 'light' | 'dark') || 'dark'
    }
    return 'dark'
  })(),
  fetchConfig: async () => {
    set({ isLoading: true, error: null })
    try {
      const res = await fetch('/api/system/config')
      if (!res.ok) throw new Error('Failed to fetch config')
      const data = await res.json()
      set({ config: data, isLoading: false })
    } catch (e) {
      set({ error: e instanceof Error ? e.message : 'Unknown error', isLoading: false })
    }
  },
  setTheme: (theme) => {
    localStorage.setItem('theme', theme)
    set({ theme })
    document.documentElement.classList.toggle('dark', theme === 'dark')
  },
  toggleTheme: () => {
    const { theme, setTheme } = get()
    setTheme(theme === 'dark' ? 'light' : 'dark')
  },
}))