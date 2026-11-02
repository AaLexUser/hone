import { useState } from 'react'

export type Theme = 'light' | 'dark'

const KEY = 'hone-theme'

function current(): Theme {
  return document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light'
}

/** The theme lives on <html data-theme>; index.html sets it before first paint. */
export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(current)
  const toggle = () => {
    const next: Theme = theme === 'dark' ? 'light' : 'dark'
    document.documentElement.dataset.theme = next
    try {
      localStorage.setItem(KEY, next)
    } catch {
      /* private mode: the toggle still works for this page view */
    }
    setTheme(next)
  }
  return [theme, toggle]
}
