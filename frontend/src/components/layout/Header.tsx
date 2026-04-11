import ThemeToggle from './ThemeToggle'

export default function Header() {
  return (
    <header className="h-14 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between px-4">
      <span className="text-lg font-semibold">Chronos Graph Dashboard</span>
      <ThemeToggle />
    </header>
  )
}