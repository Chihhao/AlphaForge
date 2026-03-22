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
    setItems(prev => {
      if (prev.some(i => i.stock_id === stock_id)) return prev
      const next = [{ stock_id, stock_name, added_at: new Date().toISOString() }, ...prev]
      save(next)
      return next
    })
  }, [])

  const remove = useCallback((stock_id: string) => {
    setItems(prev => {
      const next = prev.filter(i => i.stock_id !== stock_id)
      save(next)
      return next
    })
  }, [])

  const toggle = useCallback((stock_id: string, stock_name: string) => {
    setItems(prev => {
      const has = prev.some(i => i.stock_id === stock_id)
      const next = has
        ? prev.filter(i => i.stock_id !== stock_id)
        : [{ stock_id, stock_name, added_at: new Date().toISOString() }, ...prev]
      save(next)
      return next
    })
  }, [])

  const has = useCallback((stock_id: string) => items.some(i => i.stock_id === stock_id), [items])

  return { items, add, remove, toggle, has }
}
