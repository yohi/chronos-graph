import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './styles/globals.css'

const container = document.getElementById('root')
if (!container) {
  throw new Error(
    "Failed to find the root element. Make sure there is a <div id='root'></div> in your index.html",
  )
}

ReactDOM.createRoot(container).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)