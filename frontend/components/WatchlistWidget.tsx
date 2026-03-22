import React, { useEffect, useState } from 'react'
import Link from 'next/link'
import api from '../lib/api'
import { useWatchlist, WatchlistItem } from '../lib/useWatchlist'
import { formatPrice } from '../lib/formatters'

interface StockQuote {
  current_price: number
  change_percent: number
  stock_name: string
}

interface WatchlistRowData extends WatchlistItem {
  price?: number
  change?: number
  loading: boolean
}

interface MinerPick {
  stock_id: string
}

export default function WatchlistWidget() {
  const { items, remove } = useWatchlist()
  const [rows, setRows] = useState<WatchlistRowData[]>([])
  const [pickedIds, setPickedIds] = useState<Set<string>>(new Set())

  useEffect(() => {
    api.get<MinerPick[]>('/strategy-miner/picks/today')
      .then(r => setPickedIds(new Set((r.data ?? []).map(p => p.stock_id))))
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (items.length === 0) { setRows([]); return }

    // Initialize with loading state
    setRows(items.map(i => ({ ...i, loading: true })))

    // Fetch quotes for all watchlisted stocks
    items.forEach(item => {
      api.get<StockQuote>(`/stocks/${item.stock_id}/quote`)
        .then(r => {
          setRows(prev => prev.map(row =>
            row.stock_id === item.stock_id
              ? { ...row, price: r.data.current_price, change: r.data.change_percent, loading: false }
              : row
          ))
        })
        .catch(() => {
          setRows(prev => prev.map(row =>
            row.stock_id === item.stock_id ? { ...row, loading: false } : row
          ))
        })
    })
  }, [items])

  if (items.length === 0) return null

  return (
    <div className="bg-zinc-900/60 border border-white/10 rounded-2xl px-4 py-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-zinc-500 text-[10px] uppercase tracking-widest font-bold flex items-center gap-1.5">
          <svg viewBox="0 0 24 24" width={12} height={12} className="fill-current">
            <path d="M12,17.27L18.18,21L16.54,13.97L22,9.24L14.81,8.62L12,2L9.19,8.62L2,9.24L7.45,13.97L5.82,21L12,17.27Z" />
          </svg>
          觀察清單
        </span>
        <span className="text-zinc-700 text-[10px] font-mono">{items.length} 檔</span>
      </div>
      <div className="space-y-1">
        {rows.map(row => (
          <div key={row.stock_id} className="flex items-center justify-between py-1 group">
            <Link
              href={`/stock/${row.stock_id}`}
              className="flex items-center gap-2 min-w-0 hover:text-amber-300 transition-colors"
            >
              <span className="text-zinc-200 text-sm font-medium truncate">{row.stock_name}</span>
              <span className="text-zinc-600 text-xs font-mono shrink-0">{row.stock_id}</span>
              {pickedIds.has(row.stock_id) && (
                <span className="shrink-0 text-[9px] font-bold text-amber-400 bg-amber-500/10 border border-amber-500/25 rounded px-1 py-0.5 leading-none">
                  精選
                </span>
              )}
            </Link>
            <div className="flex items-center gap-2 ml-2 shrink-0">
              {row.loading ? (
                <span className="text-zinc-700 text-xs font-mono animate-pulse">…</span>
              ) : row.price != null ? (
                <>
                  <span className="text-zinc-300 text-sm font-mono">{formatPrice(row.price)}</span>
                  <span className={`text-xs font-mono font-bold ${(row.change ?? 0) >= 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                    {(row.change ?? 0) >= 0 ? '+' : ''}{(row.change ?? 0).toFixed(2)}%
                  </span>
                </>
              ) : (
                <span className="text-zinc-700 text-xs">—</span>
              )}
              <button
                onClick={() => remove(row.stock_id)}
                className="opacity-0 group-hover:opacity-100 text-zinc-700 hover:text-rose-400 transition-all ml-1"
                title="移除"
              >
                <svg viewBox="0 0 24 24" width={14} height={14} className="fill-current">
                  <path d="M19,6.41L17.59,5L12,10.59L6.41,5L5,6.41L10.59,12L5,17.59L6.41,19L12,13.41L17.59,19L19,17.59L13.41,12L19,6.41Z" />
                </svg>
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
