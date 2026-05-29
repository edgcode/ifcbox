import { useTheme } from '@/state/theme'

export function ThemeToggle() {
  const theme = useTheme((s) => s.theme)
  const toggle = useTheme((s) => s.toggle)
  return (
    <button
      onClick={toggle}
      title="Toggle light / dark"
      className="rounded-md border border-neutral-300 px-2 py-1 text-xs text-neutral-600 hover:bg-neutral-100 dark:border-neutral-700 dark:text-neutral-300 dark:hover:bg-neutral-800"
    >
      {theme === 'dark' ? 'Light' : 'Dark'}
    </button>
  )
}
