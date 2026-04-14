import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { configDefaults } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        ws: true,
      },
    },
  },
  test: {
    globals: true,
    environment: 'node',
    exclude: [...configDefaults.exclude, 'e2e/**'],
  },
} as any)