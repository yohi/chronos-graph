import { NavLink } from 'react-router-dom'

export default function Sidebar() {
  const navLinkClass = ({ isActive }: { isActive: boolean }) =>
    `block p-2 rounded ${
      isActive
        ? 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-200'
        : 'hover:bg-gray-100 dark:hover:bg-gray-700'
    }`

  return (
    <aside className="w-64 bg-white dark:bg-gray-800 border-r border-gray-200 dark:border-gray-700">
      <div className="p-4">
        <h1 className="text-xl font-bold">Chronos Graph</h1>
      </div>
      <nav className="p-4 space-y-2">
        <NavLink to="/" className={navLinkClass}>Dashboard</NavLink>
        <NavLink to="/network" className={navLinkClass}>Network</NavLink>
        <NavLink to="/logs" className={navLinkClass}>Logs</NavLink>
        <NavLink to="/settings" className={navLinkClass}>Settings</NavLink>
      </nav>
    </aside>
  )
}