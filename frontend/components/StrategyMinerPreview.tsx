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
  resonance_count?: number
  buy_reasons?: string[]
  stock_win_rate?: number | null
  stock_avg_return?: number | null
  stock_trade_count?: number
  stock_best_dim?: string | null
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
  resonance_count: number
  buy_reasons: string[]
  stock_win_rate: number | null
  stock_avg_return: number | null
  stock_trade_count: number
  stock_best_dim: string | null
  current_price?: number
  change_pct?: number
  quote_data_date?: string
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

/** 判斷報價是否為過期資料（盤中時 data_date 不是今天） */
function isQuoteStale(dataDate?: string): boolean {
  if (!dataDate) return false
  const now = new Date(new Date().toLocaleString('en-US', { timeZone: 'Asia/Taipei' }))
  const day = now.getDay()
  const hour = now.getHours()
  const minute = now.getMinutes()
  const isMarketOpen = day >= 1 && day <= 5 && (hour > 9 || (hour === 9 && minute >= 0)) && (hour < 13 || (hour === 13 && minute <= 30))
  if (!isMarketOpen) return false
  const todayStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
  return dataDate !== todayStr
}

function PickRow({ pick, rank }: { pick: PickPreview; rank: number }) {
  const stale = isQuoteStale(pick.quote_data_date)
  const price = stale ? null : (pick.current_price || pick.entry_price)
  const dimLabel = DIM_LABEL[pick.time_dimension] ?? ''
  const change = stale ? null : (pick.change_pct ?? 0)
  const changeColor = (change ?? 0) > 0 ? 'text-rose-400' : ((change ?? 0) < 0 ? 'text-emerald-400' : 'text-zinc-400')

  return (
    <Link
      href={`/stock/${pick.stock_id}`}
      className="flex items-center gap-2 py-2.5 px-2 rounded-lg hover:bg-white/5 transition-colors group cursor-pointer border-b border-zinc-800/40 last:border-b-0"
    >
      <span className="text-cyan-400 font-mono font-bold text-xs w-4 shrink-0 text-center">{rank}</span>
      <div className="flex flex-col min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className={`shrink-0 text-[9px] font-bold rounded px-1 py-0.5 leading-none border ${
            pick.direction === 'short'
              ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/25'
              : 'text-rose-400 bg-rose-500/10 border-rose-500/25'
          }`}>{pick.direction === 'short' ? '空' : '多'}</span>
          <span className="text-sm font-semibold text-zinc-100">{pick.stock_name}</span>
          <span className="text-xs text-zinc-500 font-mono">{pick.stock_id}</span>
          {pick.resonance_count >= 2 && (
            <span
              className="shrink-0 text-xs px-1.5 py-0.5 rounded bg-amber-900/40 text-amber-300 font-semibold"
              title={`三維度中有 ${pick.resonance_count} 個都推薦此股`}
            >
              {pick.resonance_count}維共鳴
            </span>
          )}
        </div>
        {pick.stock_win_rate !== null && (() => {
          const count = pick.stock_trade_count ?? 0
          const wr = pick.stock_win_rate!
          const ret = pick.stock_avg_return
          return (
            <div className="flex items-center gap-2 mt-0.5" title={`此股 ${dimLabel || pick.time_dimension} 歷史真實推薦平均（${count} 筆）`}>
              <span className={`text-xs font-mono ${wr >= 0.5 ? 'text-rose-400/80' : 'text-zinc-500'}`}>
                {dimLabel}勝率 {(wr * 100).toFixed(0)}%
                {count > 0 && <span className="text-zinc-500 font-normal"> ({count}筆)</span>}
              </span>
              {ret != null && (
                <>
                  <span className="text-zinc-700">|</span>
                  <span className={`text-xs font-mono ${ret >= 0 ? 'text-rose-400/80' : 'text-emerald-400'}`}>
                    平均報酬 {ret >= 0 ? '+' : ''}{ret.toFixed(1)}%
                  </span>
                </>
              )}
            </div>
          )
        })()}
      </div>

      <div className="flex flex-col items-end">
        {price != null && change != null ? (
          <>
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
          </>
        ) : (
          <span className="text-zinc-500 font-mono text-sm">—</span>
        )}
      </div>
    </Link>
  )
}

const DIM_LABEL: Record<string, string> = { '5d': '5d', '10d': '10d', '20d': '20d' }

interface DimensionRec {
  dimension: string; forward_days: number; signal_date: string
  long_picks: Array<{ rank: number; stock_id: string; stock_name: string; score: number; trigger_factors: string[]; is_stable: boolean }>
  long_win_rate: number; long_avg_return: number
  short_picks: Array<{ rank: number; stock_id: string; stock_name: string; score: number; trigger_factors: string[]; is_stable: boolean }>
  short_win_rate: number; short_avg_return: number
  ic: number; is_significant: boolean; confidence: string
}
interface RecTable { dimensions: DimensionRec[]; last_trained: string; train_period: string; test_period: string }

const VALID_DIMS = new Set(['5d', '10d', '20d'])
const cleanDim = (d: string | null | undefined) => (d && VALID_DIMS.has(d)) ? d : null

export default function StrategyMinerPreview() {
  const [picks, setPicks] = useState<PickPreview[]>([])
  const [loading, setLoading] = useState(true)
  const [pickDate, setPickDate] = useState<string | null>(null)
  const [nextTradingDay, setNextTradingDay] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    api.get<TodayPick[]>('/strategy-miner/picks/today')
      .then(picksRes => {
        if (cancelled) return
        const pd = picksRes.data?.[0]?.pick_date
        if (pd) {
          setPickDate(pd)
          api.get<{ label: string }>(`/market/next-trading-day?from_date=${pd}`)
            .then(r => { if (!cancelled && r.data?.label) setNextTradingDay(r.data.label) })
            .catch(() => {})
        }

        // 只用 Strategy Miner picks（過濾掉非活躍維度）
        const combined: PickPreview[] = (picksRes.data || [])
          .filter(p => VALID_DIMS.has(p.time_dimension))
          .map(p => {
          const dim = p.time_dimension
          return {
            stock_id: p.stock_id, stock_name: p.stock_name,
            entry_price: p.entry_price, take_profit_pct: p.take_profit_pct,
            stop_loss_pct: p.stop_loss_pct, hold_days_max: p.hold_days_max,
            weighted_score: p.weighted_score, time_dimension: dim,
            direction: p.direction || 'long',
            dims: (() => { try { return JSON.parse(p.strategy_ids).filter((d: string) => VALID_DIMS.has(d)) } catch { return [dim] } })(),
            resonance_count: p.resonance_count ?? 1,
            buy_reasons: p.buy_reasons ?? [],
            stock_win_rate: p.stock_win_rate ?? null,
            stock_avg_return: (p as any).stock_avg_return ?? null,
            stock_trade_count: p.stock_trade_count ?? 0,
            stock_best_dim: cleanDim((p as any).stock_best_dim) ?? dim,
          }
        })

        // 按信號綜合分數排序；per-dim 架構下同股可能有多筆, 去重保留最高分。
        combined.sort((a, b) => (b.weighted_score ?? 0) - (a.weighted_score ?? 0))
        const seen = new Set<string>()
        const longTop3 = combined
          .filter(p => p.direction === 'long')
          .filter(p => {
            if (seen.has(p.stock_id)) return false
            seen.add(p.stock_id)
            return true
          })
          .slice(0, 3)

        setPicks(longTop3)

        // 批次查報價
        const ids = longTop3.map(p => p.stock_id)
        Promise.allSettled(
          ids.map(id => api.get(`/stocks/${id}/quote`))
        ).then(results => {
          if (cancelled) return
          const withQuotes = longTop3.map((p, i) => {
            const r = results[i]
            if (r.status === 'fulfilled' && r.value.data) {
              return { ...p, current_price: r.value.data.current_price, change_pct: r.value.data.change_percent, quote_data_date: r.value.data.data_date }
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
          {nextTradingDay ?? todayLabel()} 操作建議
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
        <div className="py-4 text-center text-xs text-zinc-400">{nextTradingDay ?? todayLabel()} 暫無推薦</div>
      ) : (
        <>
          {picks.filter(p => p.direction === 'long').length > 0 && (
            <>
              <div className="flex items-center gap-2 px-2 pt-1 pb-1">
                <span className="w-1 h-1 rounded-full bg-rose-400" />
                <span className="text-xs font-semibold text-zinc-400">做多</span>
                <div className="flex-1 h-px bg-zinc-800/40" />
              </div>
              {picks.filter(p => p.direction === 'long').map((pick, i) => (
                <PickRow key={pick.stock_id} pick={pick} rank={i + 1} />
              ))}
            </>
          )}
          <div className="flex items-center gap-2 px-2 pt-2 pb-1">
            <span className="w-1 h-1 rounded-full bg-emerald-400" />
            <span className="text-xs font-semibold text-zinc-400">做空</span>
            <div className="flex-1 h-px bg-zinc-800/40" />
          </div>
          <p className="text-zinc-500 text-xs px-2 pb-1">目前無推薦</p>
        </>
      )}

    </div>
  )
}
