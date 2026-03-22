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
      <span className="text-gray-600">{'★'.repeat(5 - stars)}</span>
    </span>
  )
}

function SkeletonRow() {
  return (
    <div className="flex items-center justify-between py-2 border-b border-gray-700/40 animate-pulse">
      <div className="flex items-center gap-2">
        <div className="h-3 w-16 bg-gray-700 rounded" />
        <div className="h-3 w-10 bg-gray-700 rounded" />
      </div>
      <div className="h-3 w-28 bg-gray-700 rounded" />
    </div>
  )
}

function PickRow({ pick }: { pick: PickPreview }) {
  const tpPct = Math.round(pick.take_profit_pct * 100)
  const slPct = Math.round(pick.stop_loss_pct * 100)

  return (
    <div className="flex items-center justify-between py-2 border-b border-gray-700/40 last:border-b-0">
      <div className="flex items-center gap-2 min-w-0">
        <Link
          href={`/stock/${pick.stock_id}`}
          className="text-sm text-gray-200 hover:text-amber-300 transition-colors truncate"
        >
          {pick.stock_name} <span className="text-gray-500">{pick.stock_id}</span>
        </Link>
        <StarsDisplay score={pick.weighted_score} />
      </div>
      <div className="flex items-center gap-1 text-xs font-mono whitespace-nowrap ml-2 shrink-0">
        <span className="text-gray-400">買入</span>
        <span className="text-gray-200">{pick.entry_price.toFixed(0)}</span>
        <span className="text-gray-500">→</span>
        <span className="text-emerald-400">+{tpPct}%</span>
        <span className="text-gray-600">/</span>
        <span className="text-rose-400">-{slPct}%</span>
      </div>
    </div>
  )
}

const DIM_LABEL: Record<string, string> = { '5d': '5日', '10d': '10日', '30d': '30日' }

export default function StrategyMinerPreview() {
  const [picks, setPicks] = useState<PickPreview[]>([])
  const [perf, setPerf] = useState<Record<string, PerfStats>>({})
  const [loading, setLoading] = useState(true)

  useEffect(() => {
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
    <div className="bg-gray-800 rounded-lg border border-gray-700 p-4">
      {/* Header */}
      <div className="flex justify-between items-center mb-3">
        <div>
          <div className="text-sm font-bold text-gray-500 uppercase tracking-widest flex items-center gap-2">
            <svg viewBox="0 0 24 24" width={16} height={16} className="fill-current text-amber-500">
              <path d="M16,6L18.29,8.29L13.42,13.17L9.42,9.17L2,16.59L3.41,18L9.42,12L13.42,16L19.71,9.71L22,12V6H16Z" />
            </svg>
            今日精選
          </div>
          <div className="text-xs text-gray-600 mt-0.5">量化模型推薦 · 停利停損由回測自動尋優</div>
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

      {/* List */}
      {loading ? (
        <>
          <SkeletonRow />
          <SkeletonRow />
          <SkeletonRow />
        </>
      ) : picks.length === 0 ? (
        <div className="py-4 text-center text-xs text-gray-600">今日暫無推薦</div>
      ) : (
        picks.map(pick => (
          <PickRow key={pick.stock_id} pick={pick} />
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
          <div className="mt-3 pt-3 border-t border-gray-700/40 flex items-center gap-3 flex-wrap">
            <span className="text-[10px] text-gray-600 uppercase tracking-widest font-semibold">回測績效</span>
            <span className="text-[10px] font-mono text-gray-500">{dimLabel}策略</span>
            <span className={`text-[10px] font-mono font-semibold ${winRate >= 55 ? 'text-emerald-400' : winRate >= 50 ? 'text-amber-400' : 'text-rose-400'}`}>
              勝率 {winRate}%
            </span>
            <span className="text-gray-700 text-[10px]">·</span>
            <span className={`text-[10px] font-mono font-semibold ${stats.avg_return_test >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
              均報酬 {stats.avg_return_test >= 0 ? '+' : ''}{avgRet}%
            </span>
            <span className="text-gray-700 text-[10px]">·</span>
            <span className="text-[10px] font-mono text-gray-600">{stats.trade_count_test} 筆交易</span>
          </div>
        )
      })()}
    </div>
  )
}
