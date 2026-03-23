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
  const [editMode, setEditMode] = useState(false)
  const [confirmId, setConfirmId] = useState<string | null>(null)

  useEffect(() => {
    api.get<MinerPick[]>('/strategy-miner/picks/today')
      .then(r => setPickedIds(new Set((r.data ?? []).map(p => p.stock_id))))
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (items.length === 0) { setRows([]); return }

    setRows(items.map(i => ({ ...i, loading: true })))

    items.forEach(item => {
      api.get<StockQuote>(`/stocks/${item.stock_id}/quote`)
        .then(r => {
          setRows(prev => prev.map(row =>
            row.stock_id === item.stock_id
              ? {
                  ...row,
                  stock_name: r.data.stock_name || row.stock_name,
                  price: r.data.current_price,
                  change: r.data.change_percent,
                  loading: false
                }
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

  // 離開編輯模式時清除確認狀態
  useEffect(() => {
    if (!editMode) setConfirmId(null)
  }, [editMode])

  if (items.length === 0) return null

  const handleRemoveClick = (stock_id: string) => {
    if (confirmId === stock_id) {
      remove(stock_id)
      setConfirmId(null)
    } else {
      setConfirmId(stock_id)
      setTimeout(() => setConfirmId(prev => prev === stock_id ? null : prev), 3000)
    }
  }

  return (
    <div className="bg-zinc-900/60 border border-white/10 rounded-2xl px-4 py-3">
      {/* 標題列 */}
      <div className="flex items-center justify-between mb-2 pb-2 border-b border-zinc-800/40">
        <span className="text-zinc-300 text-[10px] uppercase tracking-widest font-bold flex items-center gap-1.5">
          <svg viewBox="0 0 24 24" width={12} height={12} className="fill-current">
            <path d="M12,17.27L18.18,21L16.54,13.97L22,9.24L14.81,8.62L12,2L9.19,8.62L2,9.24L7.45,13.97L5.82,21L12,17.27Z" />
          </svg>
          觀察清單
        </span>
        <div className="flex items-center gap-2">
          <span className="text-zinc-500 text-[10px] font-mono">{items.length} 檔</span>
          <button
            onClick={() => setEditMode(v => !v)}
            className={`text-[10px] font-bold px-2 py-0.5 rounded transition-all ${
              editMode
                ? 'text-white bg-zinc-700 border border-zinc-500'
                : 'text-zinc-400 hover:text-zinc-200'
            }`}
          >
            {editMode ? '完成' : '編輯'}
          </button>
        </div>
      </div>

      {/* 清單 */}
      <div>
        {rows.map((row, index) => (
          <div key={row.stock_id} className="flex items-center justify-between py-2 px-2 rounded-lg hover:bg-white/5 transition-colors border-b border-zinc-800/40 last:border-b-0">
            {/* 左側：編號 + 名稱 + 代號 + 精選badge */}
            {editMode ? (
              <div className="flex items-center gap-2 min-w-0 flex-1">
                <span className="font-mono font-bold text-xs w-4 shrink-0 text-center text-zinc-600">
                  {index + 1}
                </span>
                <span className="text-sm font-semibold text-zinc-100 truncate">{row.stock_name}</span>
                <span className="text-xs text-zinc-500 font-mono shrink-0">{row.stock_id}</span>
              </div>
            ) : (
              <Link href={`/stock/${row.stock_id}`} className="flex items-center gap-2 min-w-0 flex-1">
                <span className="font-mono font-bold text-xs w-4 shrink-0 text-center text-zinc-600">
                  {index + 1}
                </span>
                <span className="text-sm font-semibold text-zinc-100 truncate">{row.stock_name}</span>
                <span className="text-xs text-zinc-500 font-mono shrink-0">{row.stock_id}</span>
                {pickedIds.has(row.stock_id) && (
                  <span className="shrink-0 text-[9px] font-bold text-amber-400 bg-amber-500/10 border border-amber-500/25 rounded px-1 py-0.5 leading-none">
                    精選
                  </span>
                )}
              </Link>
            )}

            {/* 右側：價格 + 漲跌 / 刪除按鈕 */}
            <div className="flex items-center gap-2 shrink-0 ml-2">
              {editMode ? (
                confirmId === row.stock_id ? (
                  <button
                    onClick={() => handleRemoveClick(row.stock_id)}
                    className="text-[10px] font-bold text-rose-400 bg-rose-500/15 border border-rose-500/30 rounded px-1.5 py-0.5 leading-none transition-all"
                  >
                    確認刪除
                  </button>
                ) : (
                  <button
                    onClick={() => handleRemoveClick(row.stock_id)}
                    className="text-zinc-400 hover:text-rose-400 transition-colors"
                    title="移除"
                  >
                    <svg viewBox="0 0 24 24" width={16} height={16} className="fill-current">
                      <path d="M19,6.41L17.59,5L12,10.59L6.41,5L5,6.41L10.59,12L5,17.59L6.41,19L12,13.41L17.59,19L19,17.59L13.41,12L19,6.41Z" />
                    </svg>
                  </button>
                )
              ) : (
                <>
                  {row.loading ? (
                    <span className="text-zinc-500 text-xs font-mono animate-pulse">…</span>
                  ) : row.price != null ? (
                    <>
                      <span className="text-sm font-mono font-bold text-zinc-100">{formatPrice(row.price)}</span>
                      <span className={`text-xs font-mono font-bold w-16 text-right ${(row.change ?? 0) >= 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                        {(row.change ?? 0) >= 0 ? '▲' : '▼'} {Math.abs(row.change ?? 0).toFixed(2)}%
                      </span>
                    </>
                  ) : (
                    <span className="text-zinc-500 text-xs w-16 text-right">—</span>
                  )}
                </>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
