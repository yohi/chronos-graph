import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './styles/globals.css'

if (typeof window !== 'undefined') {
  const theme = localStorage.getItem('theme') || 'dark'
  document.documentElement.classList.toggle('dark', theme === 'dark')
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)