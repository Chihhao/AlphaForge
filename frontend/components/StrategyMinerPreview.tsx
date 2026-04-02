import React, { useEffect, useState } from 'react'
import Link from 'next/link'
import api from '../lib/api'
import { todayLabel } from '../lib/formatters'

interface TodayPick {
  pick_date: string
  stock_id: string
  stock_name: string
  strategy_ids: string
  weighted_score: number
  entry_price: number
  take_profit_pct: number
  stop_loss_pct: number
  hold_days_max: number
  time_dimension: string
  direction?: string
  buy_reasons?: string[]
  stock_win_rate?: number | null
  stock_avg_return?: number | null
  stock_best_dim?: string | null
}

interface StrategyInfo {
  strategy_id: string
  win_rate_outsample: number
  win_rate_positive: number
  avg_return_top: number
  ic: number
}

interface PickPreview {
  stock_id: string
  stock_name: string
  entry_price: number
  take_profit_pct: number
  stop_loss_pct: number
  hold_days_max: number
  weighted_score: number
  time_dimension: string
  direction: string
  dims: string[]
  buy_reasons: string[]
  stock_win_rate: number | null
  stock_avg_return: number | null
  stock_best_dim: string | null
  strategy_win_rate: number | null
  strategy_avg_return: number | null
  current_price?: number
  change_pct?: number
}


function scoreToStars(score: number): number {
  if (score >= 20) return 5
  if (score >= 15) return 4
  if (score >= 10) return 3
  if (score >= 5) return 2
  return 1
}

function StarsDisplay({ score }: { score: number }) {
  const stars = scoreToStars(score)
  return (
    <span className="text-amber-400 text-xs tracking-tight select-none">
      {'★'.repeat(stars)}
      <span className="text-zinc-700">{'★'.repeat(5 - stars)}</span>
    </span>
  )
}

function SkeletonRow() {
  return (
    <div className="flex items-center justify-between py-2 border-b border-zinc-800/50 animate-pulse">
      <div className="flex items-center gap-2">
        <div className="h-3 w-16 bg-zinc-800 rounded" />
        <div className="h-3 w-10 bg-zinc-800 rounded" />
      </div>
      <div className="h-3 w-28 bg-zinc-800 rounded" />
    </div>
  )
}

function formatPrice(price: number): string {
  if (price === 0) return '---'
  if (price < 100) return price.toFixed(2)
  if (price < 500) return price.toFixed(1)
  return Math.round(price).toString()
}

function PickRow({ pick, rank }: { pick: PickPreview; rank: number }) {
  const isMultiDim = pick.dims.length > 1
  const price = pick.current_price || pick.entry_price
  const dimLabel = DIM_LABEL[pick.time_dimension] ?? ''
  const change = pick.change_pct ?? 0
  const changeColor = change > 0 ? 'text-rose-400' : (change < 0 ? 'text-emerald-400' : 'text-zinc-400')

  return (
    <Link
      href={`/stock/${pick.stock_id}`}
      className="flex items-center gap-2 py-2.5 px-2 rounded-lg hover:bg-white/5 transition-colors group cursor-pointer border-b border-zinc-800/40 last:border-b-0"
    >
      <span className="text-cyan-400 font-mono font-bold text-xs w-4 shrink-0 text-center">{rank}</span>
      <div className="flex flex-col min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="shrink-0 text-[9px] font-bold text-rose-400 bg-rose-500/10 border border-rose-500/25 rounded px-1 py-0.5 leading-none">多</span>
          <span className="text-sm font-semibold text-zinc-100">{pick.stock_name}</span>
          <span className="text-xs text-zinc-500 font-mono">{pick.stock_id}</span>
          {isMultiDim && (
            <span className="shrink-0 text-[9px] font-bold text-cyan-400 bg-cyan-500/10 border border-cyan-500/25 rounded px-1 py-0.5 leading-none whitespace-nowrap">
              多維
            </span>
          )}
        </div>
        {(() => {
          const wr = pick.stock_win_rate ?? pick.strategy_win_rate
          const ret = pick.stock_avg_return ?? pick.strategy_avg_return
          const isStrategy = pick.stock_win_rate === null
          if (wr === null) return null
          return (
            <div className="flex items-center gap-2 mt-0.5">
              <span className={`text-xs font-mono ${wr >= 0.5 ? 'text-rose-400/80' : 'text-zinc-500'}`}>
                {dimLabel}{isStrategy ? '策略' : ''}勝率 {(wr * 100).toFixed(0)}%
              </span>
              {ret != null && (
                <>
                  <span className="text-zinc-700">|</span>
                  <span className={`text-xs font-mono ${ret >= 0 ? 'text-rose-400/80' : 'text-emerald-400'}`}>
                    預計報酬 {ret >= 0 ? '+' : ''}{ret.toFixed(1)}%
                  </span>
                </>
              )}
            </div>
          )
        })()}
      </div>

      <div className="flex flex-col items-end">
        <div className="flex items-center">
          {change > 0 && <span className="text-rose-400 text-[10px] mr-1">▲</span>}
          {change < 0 && <span className="text-emerald-400 text-[10px] mr-1">▼</span>}
          <span className={`${changeColor} font-mono font-bold text-sm`}>
            {formatPrice(price)}
          </span>
        </div>
        <span className={`${changeColor} text-xs font-bold font-mono`}>
          {change === 0 ? '0.00' : (change > 0 ? '+' : '') + change.toFixed(2)}%
        </span>
      </div>
    </Link>
  )
}

const DIM_LABEL: Record<string, string> = { '20d': '20日' }

export default function StrategyMinerPreview() {
  const [picks, setPicks] = useState<PickPreview[]>([])
  const [loading, setLoading] = useState(true)
  const [pickDate, setPickDate] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    Promise.all([
      api.get<TodayPick[]>('/strategy-miner/picks/today'),
      api.get<{ strategies: StrategyInfo[] }>('/alpha-miner/strategies'),
    ]).then(([picksRes, stratRes]) => {
        if (cancelled) return
        if (picksRes.data?.length > 0) setPickDate(picksRes.data[0].pick_date)

        // 建立策略勝率 lookup（lgb_20d → win_rate）
        const stratMap: Record<string, StrategyInfo> = {}
        for (const s of stratRes.data?.strategies ?? []) {
          stratMap[s.strategy_id] = s
        }

        const all = (picksRes.data || []).map(p => {
          // 找對應策略的勝率做 fallback
          const dimKey = p.time_dimension?.replace('d', '') ? `lgb_${p.time_dimension}` : ''
          const strat = stratMap[dimKey]
          return {
            stock_id: p.stock_id,
            stock_name: p.stock_name,
            entry_price: p.entry_price,
            take_profit_pct: p.take_profit_pct,
            stop_loss_pct: p.stop_loss_pct,
            hold_days_max: p.hold_days_max,
            weighted_score: p.weighted_score,
            time_dimension: p.time_dimension,
            direction: p.direction || 'long',
            dims: (() => { try { return JSON.parse(p.strategy_ids) } catch { return [p.time_dimension] } })(),
            buy_reasons: p.buy_reasons ?? [],
            stock_win_rate: p.stock_win_rate ?? null,
            stock_avg_return: (p as any).stock_avg_return ?? null,
            stock_best_dim: (p as any).stock_best_dim ?? null,
            strategy_win_rate: strat?.win_rate_positive ?? null,
            strategy_avg_return: strat?.avg_return_top ?? null,
          }
        })
        // 策略選股前 3（首頁預覽精簡版）
        const combined = all.filter(p => p.direction === 'long').slice(0, 3)

        setPicks(combined)  // 先顯示，報價到了再更新

        // 批次查報價
        Promise.allSettled(
          combined.map(p => api.get(`/stocks/${p.stock_id}/quote`))
        ).then(results => {
          if (cancelled) return
          const withQuotes = combined.map((p, i) => {
            const r = results[i]
            if (r.status === 'fulfilled' && r.value.data) {
              return { ...p, current_price: r.value.data.current_price, change_pct: r.value.data.change_percent }
            }
            return p
          })
          setPicks(withQuotes)
        }).finally(() => {
          if (!cancelled) setLoading(false)
        })
      })
      .catch(() => {
        if (!cancelled) { setPicks([]); setLoading(false) }
      })

    return () => { cancelled = true }
  }, [])

  return (
    <div className="bg-zinc-900/60 border border-white/10 rounded-2xl px-2 py-3">
      {/* Header */}
      <div className="flex justify-between items-center mb-2 pb-2 border-b border-zinc-800/40 px-2">
        <span className="text-amber-400 text-sm font-bold flex items-center gap-1.5">
          <svg viewBox="0 0 24 24" width={14} height={14} className="fill-current">
            <path d="M16,6L18.29,8.29L13.42,13.17L9.42,9.17L2,16.59L3.41,18L9.42,12L13.42,16L19.71,9.71L22,12V6H16Z" />
          </svg>
          {todayLabel()} 操作建議
          {pickDate && (
            <span className="text-zinc-400 text-xs font-mono font-normal ml-1">
              資料 {pickDate.split('-').slice(1).map(Number).join('/')}
            </span>
          )}
        </span>
        <Link
          href="/strategy"
          className="text-xs text-amber-500 hover:text-amber-300 transition-colors flex items-center gap-1"
        >
          查看全部
          <svg viewBox="0 0 24 24" width={12} height={12} className="fill-current">
            <path d="M8.59,16.58L13.17,12L8.59,7.41L10,6L16,12L10,18L8.59,16.58Z" />
          </svg>
        </Link>
      </div>


      {/* List */}
      {loading ? (
        <>
          <SkeletonRow />
          <SkeletonRow />
          <SkeletonRow />
        </>
      ) : picks.length === 0 ? (
        <div className="py-4 text-center text-xs text-zinc-400">{todayLabel()} 暫無推薦</div>
      ) : (
        picks.map((pick, i) => (
          <PickRow key={pick.stock_id} pick={pick} rank={i + 1} />
        ))
      )}

    </div>
  )
}
