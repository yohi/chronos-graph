import { useEffect } from 'react'
import { useSettingsStore } from '../stores/settingsStore'

export default function Settings() {
  const { config, isLoading, error, fetchConfig } = useSettingsStore()

  useEffect(() => {
    fetchConfig()
  }, [fetchConfig])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 text-red-600 dark:text-red-400">
        Error: {error}
      </div>
    )
  }

  if (!config) {
    return null
  }

  const items = [
    { label: 'Storage Backend', value: config.storageBackend },
    { label: 'Graph Backend', value: config.graphBackend },
    { label: 'Cache Backend', value: config.cacheBackend },
    { label: 'Embedding Provider', value: config.embeddingProvider },
    { label: 'Embedding Model', value: config.embeddingModel },
    { label: 'Log Level', value: config.logLevel },
    { label: 'Dashboard Port', value: config.dashboardPort.toString() },
  ]

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Settings</h1>
        <p className="text-gray-500 dark:text-gray-400">System configuration</p>
      </div>

      <div className="bg-white dark:bg-gray-800 rounded-lg shadow border border-gray-200 dark:border-gray-700">
        <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <h2 className="text-lg font-semibold">Configuration</h2>
        </div>
        <div className="divide-y divide-gray-200 dark:divide-gray-700">
          {items.map((item) => (
            <div key={item.label} className="px-6 py-4 flex justify-between items-center">
              <span className="text-gray-600 dark:text-gray-400">{item.label}</span>
              <span className="font-mono text-gray-900 dark:text-gray-100">{item.value}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}