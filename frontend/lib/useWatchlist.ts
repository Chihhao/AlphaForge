import { useState, useEffect, useCallback } from 'react'

export interface WatchlistItem {
  stock_id: string
  stock_name: string
  added_at: string  // ISO date
}

const KEY = 'alphaforge_watchlist'

function load(): WatchlistItem[] {
  if (typeof window === 'undefined') return []
  try {
    const raw = localStorage.getItem(KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function save(items: WatchlistItem[]) {
  try {
    localStorage.setItem(KEY, JSON.stringify(items))
  } catch {}
}

export function useWatchlist() {
  const [items, setItems] = useState<WatchlistItem[]>([])

  useEffect(() => {
    setItems(load())
  }, [])

  const add = useCallback((stock_id: string, stock_name: string) => {
    // 每次從 localStorage 讀最新狀態，避免多個元件實例競態覆蓋
    const current = load()
    if (current.some(i => i.stock_id === stock_id)) return
    const next = [{ stock_id, stock_name, added_at: new Date().toISOString() }, ...current]
    save(next)
    setItems(next)
  }, [])

  const remove = useCallback((stock_id: string) => {
    const current = load()
    const next = current.filter(i => i.stock_id !== stock_id)
    save(next)
    setItems(next)
  }, [])

  const toggle = useCallback((stock_id: string, stock_name: string) => {
    const current = load()
    const has = current.some(i => i.stock_id === stock_id)
    const next = has
      ? current.filter(i => i.stock_id !== stock_id)
      : [{ stock_id, stock_name, added_at: new Date().toISOString() }, ...current]
    save(next)
    setItems(next)
  }, [])

  const has = useCallback((stock_id: string) => items.some(i => i.stock_id === stock_id), [items])

  return { items, add, remove, toggle, has }
}
