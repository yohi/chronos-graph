export default function Sidebar() {
  return (
    <aside className="w-64 bg-white dark:bg-gray-800 border-r border-gray-200 dark:border-gray-700">
      <div className="p-4">
        <h1 className="text-xl font-bold">Chronos Graph</h1>
      </div>
      <nav className="p-4 space-y-2">
        <a href="/" className="block p-2 rounded hover:bg-gray-100 dark:hover:bg-gray-700">Dashboard</a>
        <a href="/network" className="block p-2 rounded hover:bg-gray-100 dark:hover:bg-gray-700">Network</a>
        <a href="/logs" className="block p-2 rounded hover:bg-gray-100 dark:hover:bg-gray-700">Logs</a>
        <a href="/settings" className="block p-2 rounded hover:bg-gray-100 dark:hover:bg-gray-700">Settings</a>
      </nav>
    </aside>
  )
}