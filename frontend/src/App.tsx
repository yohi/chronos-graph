import { useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Dashboard from './pages/Dashboard'
import NetworkView from './pages/NetworkView'
import LogExplorer from './pages/LogExplorer'
import Settings from './pages/Settings'
import Sidebar from './components/layout/Sidebar'
import Header from './components/layout/Header'
import PageContainer from './components/layout/PageContainer'

const queryClient = new QueryClient()

export default function App() {
  useEffect(() => {
    const saved = localStorage.getItem('theme')
    if (saved === 'dark') {
      document.documentElement.classList.add('dark')
    } else {
      document.documentElement.classList.remove('dark')
    }
  }, [])

  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <div className="flex h-screen bg-gray-50 dark:bg-gray-900">
          <Sidebar />
          <div className="flex-1 flex flex-col overflow-hidden">
            <Header />
            <PageContainer>
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/network" element={<NetworkView />} />
                <Route path="/logs" element={<LogExplorer />} />
                <Route path="/settings" element={<Settings />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </PageContainer>
          </div>
        </div>
      </BrowserRouter>
    </QueryClientProvider>
  )
}