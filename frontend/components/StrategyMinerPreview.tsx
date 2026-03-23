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
  dims: string[]
  buy_reasons: string[]
  stock_win_rate: number | null
}

interface PerfStats {
  win_rate_test: number
  avg_return_test: number
  trade_count_test: number
}

interface ActivePick {
  stock_id: string
  stock_name: string
  entry_price: number
  current_price: number
  float_pct: number | null
  days_held: number
  status: '持有中' | '建議停利' | '建議停損' | '到期出場' | '資料不足'
  take_profit_pct: number
  stop_loss_pct: number
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
  // 顯示最關鍵的一條買入理由（跳過"N個策略觸發"這條，優先顯示具體因子）
  const topReason = pick.buy_reasons.find(r => !r.includes('個策略')) ?? pick.buy_reasons[0]

  return (
    <div className="py-2 border-b border-zinc-800/50 last:border-b-0">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-zinc-700 font-mono text-[10px] shrink-0">{rank}</span>
          <Link
            href={`/stock/${pick.stock_id}`}
            className="text-sm font-semibold text-zinc-200 hover:text-amber-300 transition-colors truncate"
          >
            {pick.stock_name}
          </Link>
          <span className="text-zinc-600 text-xs shrink-0">{pick.stock_id}</span>
          {isMultiDim && (
            <span className="shrink-0 text-[9px] font-bold text-cyan-400 bg-cyan-500/10 border border-cyan-500/25 rounded px-1 py-0.5 leading-none whitespace-nowrap">
              多維
            </span>
          )}
        </div>
        <div className="flex items-center gap-1 text-xs font-mono whitespace-nowrap shrink-0">
          <span className="text-zinc-300">{pick.entry_price.toFixed(0)}</span>
          <span className="text-zinc-600">→</span>
          <span className="text-rose-400">+{tpPct}%</span>
          <span className="text-zinc-700">/</span>
          <span className="text-emerald-400">-{slPct}%</span>
        </div>
      </div>
      {topReason && (
        <div className="ml-5 mt-0.5 flex items-center gap-2">
          <span className="text-[10px] text-amber-400/70">{topReason}</span>
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
  const [exitAlerts, setExitAlerts] = useState<ActivePick[]>([])

  useEffect(() => {
    // 非阻塞載入出場提醒
    api.get<ActivePick[]>('/strategy-miner/picks/active')
      .then(r => {
        const alerts = (r.data || []).filter(p => !['持有中', '資料不足'].includes(p.status))
        setExitAlerts(alerts)
      })
      .catch(() => {})

    Promise.all([
      api.get<TodayPick[]>('/strategy-miner/picks/today'),
      api.get<Record<string, PerfStats>>('/strategy-miner/performance'),
    ])
      .then(([picksRes, perfRes]) => {
        const top3 = (picksRes.data || []).slice(0, 5).map(p => ({
          stock_id: p.stock_id,
          stock_name: p.stock_name,
          entry_price: p.entry_price,
          take_profit_pct: p.take_profit_pct,
          stop_loss_pct: p.stop_loss_pct,
          hold_days_max: p.hold_days_max,
          weighted_score: p.weighted_score,
          time_dimension: p.time_dimension,
          dims: (() => { try { return JSON.parse(p.strategy_ids) } catch { return [p.time_dimension] } })(),
          buy_reasons: p.buy_reasons ?? [],
          stock_win_rate: p.stock_win_rate ?? null,
        }))
        setPicks(top3)
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
      <div className="flex justify-between items-center mb-3">
        <div>
          <div className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest flex items-center gap-2">
            <svg viewBox="0 0 24 24" width={16} height={16} className="fill-rose-400">
              <path d="M16,6L18.29,8.29L13.42,13.17L9.42,9.17L2,16.59L3.41,18L9.42,12L13.42,16L19.71,9.71L22,12V6H16Z" />
            </svg>
            明日建議買入
          </div>
          <div className="text-xs text-zinc-600 mt-0.5">量化多策略共振 · 停利停損由回測優化</div>
        </div>
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

      {/* 今日建議賣出（出場提醒） */}
      {exitAlerts.length > 0 && (
        <div className="mb-3 border border-amber-500/20 bg-amber-500/5 rounded-xl px-3 py-2.5">
          <div className="flex items-center gap-1.5 mb-2">
            <svg viewBox="0 0 24 24" width={12} height={12} className="fill-amber-400 shrink-0">
              <path d="M13,14H11V10H13M13,18H11V16H13M1,21H23L12,2L1,21Z" />
            </svg>
            <span className="text-[10px] font-bold text-amber-400 uppercase tracking-widest">今日建議賣出</span>
            <span className="text-[10px] text-amber-500/60 font-mono">{exitAlerts.length} 檔</span>
          </div>
          <div className="space-y-1.5">
            {exitAlerts.map((p, i) => {
              const STATUS_LABEL: Record<string, string> = { '建議停利': '停利', '建議停損': '停損', '到期出場': '到期' }
              const STATUS_COLOR: Record<string, string> = {
                '建議停利': 'text-rose-400',
                '建議停損': 'text-emerald-400',
                '到期出場': 'text-amber-400',
              }
              return (
                <div key={i} className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-1.5 min-w-0">
                    <Link href={`/stock/${p.stock_id}`} className="text-sm font-semibold text-zinc-200 hover:text-amber-300 transition-colors truncate">
                      {p.stock_name}
                    </Link>
                    <span className="text-zinc-600 text-xs shrink-0">{p.stock_id}</span>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {p.float_pct !== null && (
                      <span className={`text-xs font-mono font-bold ${p.float_pct >= 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                        {p.float_pct >= 0 ? '+' : ''}{p.float_pct.toFixed(1)}%
                      </span>
                    )}
                    <span className={`text-[10px] font-bold ${STATUS_COLOR[p.status] ?? 'text-amber-400'}`}>
                      {STATUS_LABEL[p.status] ?? p.status}
                    </span>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* List */}
      {loading ? (
        <>
          <SkeletonRow />
          <SkeletonRow />
          <SkeletonRow />
        </>
      ) : picks.length === 0 ? (
        <div className="py-4 text-center text-xs text-zinc-600">今日暫無推薦</div>
      ) : (
        picks.map((pick, i) => (
          <PickRow key={pick.stock_id} pick={pick} rank={i + 1} />
        ))
      )}

      {/* 回測績效摘要 */}
      {!loading && picks.length > 0 && (() => {
        const dim = picks[0].time_dimension
        const stats = perf[dim]
        if (!stats) return null
        const winRate = Math.round(stats.win_rate_test * 100)
        const avgRet = stats.avg_return_test.toFixed(1)
        const dimLabel = DIM_LABEL[dim] ?? dim
        return (
          <div className="mt-3 pt-3 border-t border-zinc-800/50 flex items-center gap-3 flex-wrap">
            <span className="text-[10px] text-zinc-600 uppercase tracking-widest font-semibold">回測績效</span>
            <span className="text-[10px] font-mono text-zinc-500">{dimLabel}策略</span>
            <span className={`text-[10px] font-mono font-semibold ${winRate >= 55 ? 'text-rose-400' : winRate >= 50 ? 'text-amber-400' : 'text-zinc-500'}`}>
              勝率 {winRate}%
            </span>
            <span className="text-zinc-700 text-[10px]">·</span>
            <span className={`text-[10px] font-mono font-semibold ${stats.avg_return_test >= 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
              均報酬 {stats.avg_return_test >= 0 ? '+' : ''}{avgRet}%
            </span>
            <span className="text-zinc-700 text-[10px]">·</span>
            <span className="text-[10px] font-mono text-zinc-600">{stats.trade_count_test} 筆交易</span>
          </div>
        )
      })()}
    </div>
  )
}
