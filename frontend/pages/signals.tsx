import React, { useEffect, useState } from 'react'
import Head from 'next/head'
import Link from 'next/link'
import api from '../lib/api'

interface TodaySignal {
    stock_id: string
    stock_name: string
    trigger_count: number
    strategies: string[]
    signal_date: string
    time_dimension: string
    threshold_low: number
    threshold_high: number
    weighted_odds_ratio: number
    weighted_odds_ratio_hi: number
    weighted_win_rate: number
    weighted_win_rate_hi: number
    weighted_loss_rate: number
    weighted_loss_rate_hi: number
    weighted_market_win_rate: number
    weighted_market_win_rate_hi: number
    weighted_market_loss_rate: number
    weighted_market_loss_rate_hi: number
}

type DimKey = '5d' | '10d' | '30d'
const DIM_CONFIG: Record<DimKey, { label: string; shortLabel: string; desc: string }> = {
    '5d':  { label: '5日持有',  shortLabel: '5日',  desc: '門檻 3% / 5%' },
    '10d': { label: '10日持有', shortLabel: '10日', desc: '門檻 3% / 5%' },
    '30d': { label: '30日持有', shortLabel: '30日', desc: '門檻 5% / 10%' },
}

const toPct = (v: number) => `${(v * 100).toFixed(1)}%`
const oddsColor = (v: number) =>
    v >= 1.2 ? 'text-amber-400' : v >= 1.0 ? 'text-zinc-200' : 'text-rose-400'

const Skeleton = ({ className = '' }: { className?: string }) => (
    <div className={`animate-pulse bg-zinc-800/60 rounded-xl ${className}`} />
)

const TriggerBadge = ({ count }: { count: number }) => {
    if (count >= 20) return (
        <span className="px-2.5 py-1 rounded-full text-xs font-bold bg-amber-500/20 text-amber-400 border border-amber-500/30 shrink-0">
            {count} 策略共鳴
        </span>
    )
    if (count >= 10) return (
        <span className="px-2.5 py-1 rounded-full text-xs font-bold bg-emerald-500/15 text-emerald-400 border border-emerald-500/25 shrink-0">
            {count} 策略共鳴
        </span>
    )
    return (
        <span className="px-2.5 py-1 rounded-full text-xs font-bold bg-zinc-700 text-zinc-300 border border-zinc-600 shrink-0">
            {count} 策略共鳴
        </span>
    )
}

export default function SignalsPage() {
    const [signals, setSignals] = useState<TodaySignal[]>([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [expandedId, setExpandedId] = useState<string | null>(null)
    const [dim, setDim] = useState<DimKey>('10d')

    useEffect(() => {
        setLoading(true)
        setError(null)
        api.get(`/alpha-miner/signals/today?dimension=${dim}`)
            .then(r => { setSignals(r.data); setLoading(false) })
            .catch(e => { setError(e.message); setLoading(false) })
    }, [dim])

    const tlo = dim === '30d' ? 5 : 3
    const thi = dim === '30d' ? 10 : 5

    const signalDate = signals[0]?.signal_date ?? ''
    const topCount = signals.filter(s => s.trigger_count >= 20).length
    const midCount = signals.filter(s => s.trigger_count >= 10 && s.trigger_count < 20).length

    return (
        <>
            <Head><title>今日最強訊號 | AlphaForge</title></Head>
            <div className="min-h-[calc(100vh-64px)] flex flex-col gap-4 sm:gap-6 max-w-7xl mx-auto px-3 sm:px-6 lg:px-8 py-4 sm:py-8">

                {/* ── Header ──────────────────────────────────────────── */}
                <div className="relative overflow-hidden bg-zinc-900/40 border border-zinc-800/60 rounded-2xl sm:rounded-3xl p-4 sm:p-8">
                    <div className="absolute top-0 right-0 w-48 h-48 sm:w-64 sm:h-64 bg-amber-500/5 rounded-full blur-3xl -mr-24 -mt-24 pointer-events-none" />
                    <div className="relative flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                        <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-1">
                                <svg viewBox="0 0 24 24" width={18} height={18} className="fill-amber-400 shrink-0">
                                    <path d="M7,2V13H10V22L17,11H13L17,2H7Z" />
                                </svg>
                                <h1 className="text-2xl sm:text-4xl font-bold tracking-tight text-white leading-tight">
                                    今日最強訊號
                                </h1>
                            </div>
                            <p className="text-zinc-500 text-sm sm:text-base mt-1.5 leading-relaxed">
                                {signalDate
                                    ? `${signalDate} · 多策略共鳴 · IC 加權歷史勝率`
                                    : loading ? '載入中…' : 'Alpha Miner 多因子訊號聚合'}
                            </p>
                        </div>

                    </div>
                </div>

                {/* ── Error ───────────────────────────────────────────── */}
                {error && (
                    <div className="bg-rose-900/20 border border-rose-800/50 rounded-2xl p-4 text-rose-400 text-sm">
                        載入失敗：{error}
                    </div>
                )}

                {/* ── Dimension Tabs ──────────────────────────────────── */}
                <div className="flex gap-2">
                    {(Object.keys(DIM_CONFIG) as DimKey[]).map(key => {
                        const cfg = DIM_CONFIG[key]
                        const active = dim === key
                        return (
                            <button
                                key={key}
                                onClick={() => setDim(key)}
                                className={`flex-1 sm:flex-none px-3 sm:px-5 py-2.5 sm:py-2 rounded-xl text-sm font-semibold transition-all duration-200 border cursor-pointer ${
                                    active
                                        ? 'bg-amber-500/10 border-amber-500/50 text-amber-400 shadow-sm shadow-amber-500/10'
                                        : 'bg-zinc-900/40 border-zinc-800 text-zinc-500 hover:text-zinc-200 hover:border-zinc-600'
                                }`}
                            >
                                <span className="sm:hidden">{cfg.shortLabel}</span>
                                <span className="hidden sm:inline">{cfg.label}</span>
                                {active && (
                                    <span className="hidden sm:inline text-xs ml-2 opacity-50">{cfg.desc}</span>
                                )}
                            </button>
                        )
                    })}
                </div>

                {/* ── Signal List ─────────────────────────────────────── */}
                <div className="flex-1">
                    {/* Stats banner */}
                    {!loading && signals.length > 0 && (
                        <div className="flex items-center gap-2 mb-3 px-1 flex-wrap">
                            <span className="text-zinc-600 text-xs uppercase tracking-widest">訊號分布</span>
                            <span className="text-amber-400 font-bold text-xs">{topCount}</span>
                            <span className="text-zinc-500 text-xs">超強共鳴<span className="hidden sm:inline">（≥20 策略）</span></span>
                            <span className="text-zinc-700 text-xs">·</span>
                            <span className="text-emerald-400 font-bold text-xs">{midCount}</span>
                            <span className="text-zinc-500 text-xs">強共鳴<span className="hidden sm:inline">（10–19 策略）</span></span>
                            <span className="text-zinc-700 text-xs">·</span>
                            <span className="text-zinc-300 font-bold text-xs">{signals.length - topCount - midCount}</span>
                            <span className="text-zinc-500 text-xs">一般<span className="hidden sm:inline">（&lt;10 策略）</span></span>
                        </div>
                    )}

                    {/* Loading skeleton */}
                    {loading && (
                        <div className="space-y-2.5">
                            {Array(6).fill(0).map((_, i) => <Skeleton key={i} className="h-28" />)}
                        </div>
                    )}

                    {/* Empty state */}
                    {!loading && !error && signals.length === 0 && (
                        <div className="h-40 flex flex-col items-center justify-center gap-2 text-zinc-600 text-sm bg-zinc-900/30 border border-zinc-800 rounded-2xl">
                            <svg viewBox="0 0 24 24" width={32} height={32} className="fill-zinc-700">
                                <path d="M7,2V13H10V22L17,11H13L17,2H7Z" />
                            </svg>
                            今日暫無訊號（Alpha Miner 模型訓練後自動產生）
                        </div>
                    )}

                    {/* Signal cards */}
                    {!loading && signals.length > 0 && (
                        <div className="space-y-2.5">
                            {signals.map(s => {
                                const isExpanded = expandedId === s.stock_id
                                const isTop = s.trigger_count >= 20
                                const isMid = s.trigger_count >= 10 && s.trigger_count < 20

                                return (
                                    <div
                                        key={s.stock_id}
                                        className={`rounded-2xl border transition-colors duration-200 overflow-hidden ${
                                            isExpanded
                                                ? isTop ? 'border-amber-500/50 bg-amber-500/5'
                                                    : isMid ? 'border-emerald-500/40 bg-emerald-500/5'
                                                    : 'border-zinc-700 bg-zinc-800/40'
                                                : isTop ? 'border-amber-500/25 bg-amber-500/5 hover:border-amber-500/40'
                                                    : isMid ? 'border-emerald-500/20 bg-emerald-500/5 hover:border-emerald-500/35'
                                                    : 'border-zinc-800 bg-zinc-900/40 hover:border-zinc-700'
                                        }`}
                                    >
                                        <button
                                            onClick={() => setExpandedId(isExpanded ? null : s.stock_id)}
                                            className="w-full text-left px-4 py-4 cursor-pointer active:bg-zinc-800/30"
                                        >
                                            {/* Row 1: Name + Badge */}
                                            <div className="flex items-center gap-2.5 mb-3.5">
                                                <div className="flex-1 min-w-0 flex items-baseline gap-1.5">
                                                    <p className="text-zinc-100 text-base font-semibold leading-snug truncate">{s.stock_name}</p>
                                                    <p className="text-zinc-500 text-xs font-mono shrink-0">{s.stock_id}</p>
                                                </div>
                                                <div className="flex items-center gap-1.5 shrink-0">
                                                    <span className="px-1.5 py-0.5 rounded-md text-[10px] font-semibold bg-zinc-700/60 text-zinc-400 border border-zinc-700">
                                                        {DIM_CONFIG[dim].shortLabel}後
                                                    </span>
                                                    <TriggerBadge count={s.trigger_count} />
                                                </div>
                                            </div>

                                            {/* Row 2: 雙欄統計 */}
                                            <div className="grid grid-cols-2 gap-2">
                                                {/* 左欄：漲跌 tlo% */}
                                                <div className="bg-zinc-800/50 rounded-xl px-2.5 py-1.5 space-y-0.5">
                                                    <p className="text-zinc-400 text-xs text-center mb-1">漲跌{tlo}%</p>
                                                    <div className="flex justify-between items-baseline">
                                                        <span className="text-zinc-400 text-xs">賠率比</span>
                                                        <span className={`text-base font-bold font-mono ${oddsColor(s.weighted_odds_ratio)}`}>
                                                            {s.weighted_odds_ratio.toFixed(2)}x
                                                        </span>
                                                    </div>
                                                    <div className="flex justify-between items-baseline">
                                                        <span className="text-zinc-400 text-xs">&gt;{tlo}% 勝率</span>
                                                        <span className={`text-base font-bold font-mono ${s.weighted_win_rate > s.weighted_market_win_rate ? 'text-emerald-400' : 'text-rose-400'}`}>
                                                            {toPct(s.weighted_win_rate)}
                                                        </span>
                                                    </div>
                                                    <div className="flex justify-between items-baseline">
                                                        <span className="text-zinc-400 text-xs">&lt;-{tlo}% 踩雷</span>
                                                        <span className={`text-base font-bold font-mono ${s.weighted_loss_rate < s.weighted_market_loss_rate ? 'text-emerald-400' : 'text-rose-400'}`}>
                                                            {toPct(s.weighted_loss_rate)}
                                                        </span>
                                                    </div>
                                                </div>
                                                {/* 右欄：漲跌 thi% */}
                                                <div className="bg-zinc-800/50 rounded-xl px-2.5 py-1.5 space-y-0.5">
                                                    <p className="text-zinc-400 text-xs text-center mb-1">漲跌{thi}%</p>
                                                    <div className="flex justify-between items-baseline">
                                                        <span className="text-zinc-400 text-xs">賠率比</span>
                                                        <span className={`text-base font-bold font-mono ${oddsColor(s.weighted_odds_ratio_hi)}`}>
                                                            {s.weighted_odds_ratio_hi.toFixed(2)}x
                                                        </span>
                                                    </div>
                                                    <div className="flex justify-between items-baseline">
                                                        <span className="text-zinc-400 text-xs">&gt;{thi}% 勝率</span>
                                                        <span className={`text-base font-bold font-mono ${s.weighted_win_rate_hi > s.weighted_market_win_rate_hi ? 'text-emerald-400' : 'text-rose-400'}`}>
                                                            {toPct(s.weighted_win_rate_hi)}
                                                        </span>
                                                    </div>
                                                    <div className="flex justify-between items-baseline">
                                                        <span className="text-zinc-400 text-xs">&lt;-{thi}% 踩雷</span>
                                                        <span className={`text-base font-bold font-mono ${s.weighted_loss_rate_hi < s.weighted_market_loss_rate_hi ? 'text-emerald-400' : 'text-rose-400'}`}>
                                                            {toPct(s.weighted_loss_rate_hi)}
                                                        </span>
                                                    </div>
                                                </div>
                                            </div>

                                            {/* 小字說明 */}
                                            <p className="text-[10px] text-zinc-600 mt-1.5">
                                                {s.trigger_count} 個觸發策略的歷史統計（IC 加權）
                                            </p>

                                            {/* Strategy tags */}
                                            <div className="flex flex-wrap gap-1.5 mt-2">
                                                {(isExpanded ? s.strategies : s.strategies.slice(0, 3)).map((name, i) => (
                                                    <span
                                                        key={i}
                                                        className="px-2 py-0.5 bg-zinc-700/50 text-zinc-400 rounded-full text-[10px] leading-relaxed"
                                                    >
                                                        {name}
                                                    </span>
                                                ))}
                                                {!isExpanded && s.strategies.length > 3 && (
                                                    <span className="px-2 py-0.5 text-zinc-600 text-[10px] leading-relaxed">
                                                        +{s.strategies.length - 3} 個
                                                    </span>
                                                )}
                                            </div>
                                        </button>

                                        {/* Expanded action */}
                                        {isExpanded && (
                                            <div
                                                className="px-4 pb-4 pt-3 border-t border-zinc-700/50 flex justify-between items-center"
                                                onClick={e => e.stopPropagation()}
                                            >
                                                <span className="text-zinc-600 text-xs">共 {s.strategies.length} 個策略觸發</span>
                                                <Link
                                                    href={`/stock/${s.stock_id}`}
                                                    className="px-3 py-1.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs rounded-lg transition-colors font-medium"
                                                >
                                                    查看個股 →
                                                </Link>
                                            </div>
                                        )}
                                    </div>
                                )
                            })}
                        </div>
                    )}
                </div>

                {/* ── Footer Disclaimer ───────────────────────────────── */}
                {!loading && signals.length > 0 && (
                    <p className="text-zinc-600 text-xs text-center pb-2">
                        AlphaForge 為學習型工具，訊號為歷史統計參考，不構成投資建議。
                    </p>
                )}
            </div>
        </>
    )
}
