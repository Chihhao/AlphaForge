import React, { useEffect, useState } from 'react'
import Link from 'next/link'
import api from '../lib/api'

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
  current_price?: number
  change_pct?: number
}

interface PerfStats {
  win_rate_test: number
  avg_return_test: number
  trade_count_test: number
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

function PickRow({ pick, rank }: { pick: PickPreview; rank: number }) {
  const tpPct = Math.round(pick.take_profit_pct * 100)
  const slPct = Math.round(pick.stop_loss_pct * 100)
  const isMultiDim = pick.dims.length > 1
  const isShort = pick.direction === 'short'
  const topReason = pick.buy_reasons.find(r => !r.includes('個策略')) ?? pick.buy_reasons[0]

  return (
    <div className="py-2.5 px-2 rounded-lg hover:bg-white/5 transition-colors border-b border-zinc-800/40 last:border-b-0">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-zinc-600 font-mono text-[10px] shrink-0">{rank}</span>
          {isShort ? (
            <span className="shrink-0 text-[9px] font-bold text-rose-400 bg-rose-500/10 border border-rose-500/25 rounded px-1 py-0.5 leading-none">空</span>
          ) : (
            <span className="shrink-0 text-[9px] font-bold text-emerald-400 bg-emerald-500/10 border border-emerald-500/25 rounded px-1 py-0.5 leading-none">多</span>
          )}
          <Link
            href={`/stock/${pick.stock_id}`}
            className="text-sm font-semibold text-zinc-100 hover:text-amber-300 transition-colors truncate"
          >
            {pick.stock_name}
          </Link>
          <span className="text-xs text-zinc-500 shrink-0">{pick.stock_id}</span>
          {isMultiDim && (
            <span className="shrink-0 text-[9px] font-bold text-cyan-400 bg-cyan-500/10 border border-cyan-500/25 rounded px-1 py-0.5 leading-none whitespace-nowrap">
              多維
            </span>
          )}
        </div>
        <div className="text-right shrink-0">
          {pick.current_price ? (
            <>
              <div className={`text-sm font-bold tabular-nums ${(pick.change_pct ?? 0) >= 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                {(pick.change_pct ?? 0) >= 0 ? '▲' : '▼'} {pick.current_price.toLocaleString()}
              </div>
              <div className={`text-[10px] font-mono tabular-nums ${(pick.change_pct ?? 0) >= 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                {(pick.change_pct ?? 0) >= 0 ? '+' : ''}{(pick.change_pct ?? 0).toFixed(2)}%
              </div>
            </>
          ) : (
            <div className="text-sm font-mono text-zinc-400 tabular-nums">{pick.entry_price.toFixed(0)}</div>
          )}
        </div>
      </div>
      {topReason && (
        <div className="ml-5 mt-0.5 flex items-center gap-2">
          <span className={`text-[10px] ${isShort ? 'text-rose-400/70' : 'text-amber-400/70'}`}>{topReason}</span>
          {pick.stock_win_rate !== null && (
            <span className={`text-[10px] font-mono ${pick.stock_win_rate >= 0.5 ? 'text-rose-400/70' : 'text-zinc-500'}`}>
              歷史勝率 {(pick.stock_win_rate * 100).toFixed(0)}%
            </span>
          )}
        </div>
      )}
    </div>
  )
}

const DIM_LABEL: Record<string, string> = { '5d': '5日', '10d': '10日', '30d': '30日' }

export default function StrategyMinerPreview() {
  const [picks, setPicks] = useState<PickPreview[]>([])
  const [perf, setPerf] = useState<Record<string, PerfStats>>({})
  const [loading, setLoading] = useState(true)
  const [livePerf, setLivePerf] = useState<{ trade_count: number; win_rate: number | null; avg_return: number | null } | null>(null)
  const [pickDate, setPickDate] = useState<string | null>(null)

  useEffect(() => {
    // 即時績效

    api.get('/strategy-miner/picks/live-performance')
      .then(r => setLivePerf(r.data))
      .catch(() => {})

    Promise.all([
      api.get<TodayPick[]>('/strategy-miner/picks/today'),
      api.get<Record<string, PerfStats>>('/strategy-miner/performance'),
    ])
      .then(([picksRes, perfRes]) => {
        if (picksRes.data?.length > 0) setPickDate(picksRes.data[0].pick_date)
        const all = (picksRes.data || []).map(p => ({
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
        }))
        // 做多前 3 + 放空前 3（首頁預覽精簡版）
        const longs = all.filter(p => p.direction === 'long').slice(0, 3)
        const shorts = all.filter(p => p.direction === 'short').slice(0, 3)
        const combined = [...longs, ...shorts]

        // 批次查報價
        Promise.allSettled(
          combined.map(p => api.get(`/stocks/${p.stock_id}/quote`))
        ).then(results => {
          const withQuotes = combined.map((p, i) => {
            const r = results[i]
            if (r.status === 'fulfilled' && r.value.data) {
              return { ...p, current_price: r.value.data.current_price, change_pct: r.value.data.change_percent }
            }
            return p
          })
          setPicks(withQuotes)
        })

        setPicks(combined)  // 先顯示，報價到了再更新
        setPerf(perfRes.data || {})
      })
      .catch(() => {
        setPicks([])
      })
      .finally(() => {
        setLoading(false)
      })
  }, [])

  return (
    <div className="bg-zinc-900/60 border border-white/10 rounded-2xl px-4 py-3">
      {/* Header */}
      <div className="flex justify-between items-center mb-3 pb-2 border-b border-zinc-800/40">
        <span className="text-amber-400 text-sm font-bold flex items-center gap-1.5">
          <svg viewBox="0 0 24 24" width={14} height={14} className="fill-current">
            <path d="M16,6L18.29,8.29L13.42,13.17L9.42,9.17L2,16.59L3.41,18L9.42,12L13.42,16L19.71,9.71L22,12V6H16Z" />
          </svg>
          今日操作建議
          {pickDate && (
            <span className="text-zinc-400 text-[10px] font-mono font-normal ml-1">{pickDate}</span>
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
        <div className="py-4 text-center text-xs text-zinc-400">今日暫無推薦</div>
      ) : (
        picks.map((pick, i) => (
          <PickRow key={pick.stock_id} pick={pick} rank={i + 1} />
        ))
      )}

      {/* 即時追蹤績效（優先）或回測績效（備用）*/}
      {!loading && picks.length > 0 && (() => {
        // 優先顯示即時績效
        if (livePerf && livePerf.trade_count > 0 && livePerf.win_rate !== null) {
          const winRate = Math.round(livePerf.win_rate * 100)
          return (
            <div className="mt-3 pt-3 border-t border-zinc-800/50 flex items-center gap-3 flex-wrap">
              <span className="text-[10px] text-zinc-400 uppercase tracking-widest font-semibold">即時追蹤</span>
              <span className="text-[10px] font-mono text-zinc-500">{livePerf.trade_count} 筆已出場</span>
              <span className={`text-[10px] font-mono font-semibold ${winRate >= 60 ? 'text-rose-400' : winRate >= 50 ? 'text-amber-400' : 'text-zinc-500'}`}>
                勝率 {winRate}%
              </span>
              {livePerf.avg_return !== null && (
                <>
                  <span className="text-zinc-700 text-[10px]">·</span>
                  <span className={`text-[10px] font-mono font-semibold ${livePerf.avg_return >= 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                    均{livePerf.avg_return >= 0 ? '+' : ''}{livePerf.avg_return.toFixed(1)}%
                  </span>
                </>
              )}
            </div>
          )
        }
        // 備用：回測績效
        const dim = picks[0].time_dimension
        const stats = perf[dim]
        if (!stats) return null
        const winRate = Math.round(stats.win_rate_test * 100)
        const avgRet = stats.avg_return_test.toFixed(1)
        const dimLabel = DIM_LABEL[dim] ?? dim
        return (
          <div className="mt-3 pt-3 border-t border-zinc-800/50 flex items-center gap-3 flex-wrap">
            <span className="text-[10px] text-zinc-400 uppercase tracking-widest font-semibold">回測績效</span>
            <span className="text-[10px] font-mono text-zinc-500">{dimLabel}策略</span>
            <span className={`text-[10px] font-mono font-semibold ${winRate >= 55 ? 'text-rose-400' : winRate >= 50 ? 'text-amber-400' : 'text-zinc-500'}`}>
              勝率 {winRate}%
            </span>
            <span className="text-zinc-700 text-[10px]">·</span>
            <span className={`text-[10px] font-mono font-semibold ${stats.avg_return_test >= 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
              均報酬 {stats.avg_return_test >= 0 ? '+' : ''}{avgRet}%
            </span>
          </div>
        )
      })()}
    </div>
  )
}
