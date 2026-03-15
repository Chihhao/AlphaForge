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
}

const Skeleton = ({ className = '' }: { className?: string }) => (
    <div className={`animate-pulse bg-zinc-800/60 rounded-2xl ${className}`} />
)

const TriggerBadge = ({ count }: { count: number }) => {
    if (count >= 20) return (
        <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-amber-500/20 text-amber-400 border border-amber-500/30">
            {count} 策略共鳴
        </span>
    )
    if (count >= 10) return (
        <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-emerald-500/15 text-emerald-400 border border-emerald-500/25">
            {count} 策略共鳴
        </span>
    )
    return (
        <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-zinc-700 text-zinc-300 border border-zinc-600">
            {count} 策略共鳴
        </span>
    )
}

export default function SignalsPage() {
    const [signals, setSignals] = useState<TodaySignal[]>([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [expandedId, setExpandedId] = useState<string | null>(null)

    useEffect(() => {
        api.get('/alpha-miner/signals/today')
            .then(r => { setSignals(r.data); setLoading(false) })
            .catch(e => { setError(e.message); setLoading(false) })
    }, [])

    const signalDate = signals[0]?.signal_date ?? ''
    const topCount = signals.filter(s => s.trigger_count >= 20).length
    const midCount = signals.filter(s => s.trigger_count >= 10 && s.trigger_count < 20).length

    return (
        <>
            <Head><title>今日最強訊號 | AlphaForge</title></Head>
            <div className="min-h-[calc(100vh-64px)] p-4 sm:p-6 lg:p-8 flex flex-col gap-5 max-w-7xl mx-auto">

                {/* Header */}
                <div className="relative overflow-hidden bg-zinc-900/30 border border-zinc-800/50 rounded-3xl p-5 sm:p-7">
                    <div className="absolute top-0 right-0 w-64 h-64 bg-amber-500/5 rounded-full blur-3xl -mr-24 -mt-24 pointer-events-none" />
                    <div className="relative flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                        <div>
                            <div className="flex items-center gap-2 mb-1">
                                <svg viewBox="0 0 24 24" width={20} height={20} className="fill-amber-400 shrink-0">
                                    <path d="M7,2V13H10V22L17,11H13L17,2H7Z" />
                                </svg>
                                <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-white">
                                    今日最強訊號
                                </h1>
                            </div>
                            <p className="text-zinc-400 text-sm pl-1 border-l-2 border-amber-500/30">
                                {signalDate
                                    ? `${signalDate} · 多策略共鳴選股，勝率歷史統計參考`
                                    : loading ? '載入中…' : 'Alpha Miner 多因子訊號聚合'}
                            </p>
                        </div>

                        {!loading && signals.length > 0 && (
                            <div className="flex items-center gap-2 shrink-0">
                                <div className="px-3 py-1.5 bg-zinc-950 border border-zinc-800 rounded-xl flex items-center gap-2 text-xs">
                                    <span className="relative flex h-2 w-2">
                                        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75" />
                                        <span className="relative inline-flex rounded-full h-2 w-2 bg-amber-500" />
                                    </span>
                                    <span className="text-zinc-300 font-bold tracking-widest uppercase">Live</span>
                                </div>
                                <span className="text-zinc-500 text-xs">{signals.length} 檔</span>
                            </div>
                        )}
                    </div>

                    {/* Stats bar */}
                    {!loading && signals.length > 0 && (
                        <div className="relative mt-4 flex flex-wrap gap-3">
                            <div className="flex items-center gap-2 px-3 py-2 bg-amber-500/10 border border-amber-500/20 rounded-xl text-xs">
                                <span className="text-amber-400 font-bold">{topCount}</span>
                                <span className="text-zinc-400">超強共鳴（≥20 策略）</span>
                            </div>
                            <div className="flex items-center gap-2 px-3 py-2 bg-emerald-500/10 border border-emerald-500/20 rounded-xl text-xs">
                                <span className="text-emerald-400 font-bold">{midCount}</span>
                                <span className="text-zinc-400">強共鳴（10–19 策略）</span>
                            </div>
                            <div className="flex items-center gap-2 px-3 py-2 bg-zinc-800/60 border border-zinc-700 rounded-xl text-xs">
                                <span className="text-zinc-300 font-bold">{signals.length - topCount - midCount}</span>
                                <span className="text-zinc-400">一般訊號（&lt;10 策略）</span>
                            </div>
                        </div>
                    )}
                </div>

                {/* Error */}
                {error && (
                    <div className="bg-rose-900/20 border border-rose-800/50 rounded-2xl p-4 text-rose-400 text-sm">
                        載入失敗：{error}
                    </div>
                )}

                {/* Loading skeleton */}
                {loading && (
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                        {Array(9).fill(0).map((_, i) => <Skeleton key={i} className="h-24" />)}
                    </div>
                )}

                {/* Empty state */}
                {!loading && !error && signals.length === 0 && (
                    <div className="flex-1 flex flex-col items-center justify-center py-20 gap-3">
                        <svg viewBox="0 0 24 24" width={48} height={48} className="fill-zinc-700">
                            <path d="M7,2V13H10V22L17,11H13L17,2H7Z" />
                        </svg>
                        <p className="text-zinc-500 text-sm">今日暫無訊號</p>
                        <p className="text-zinc-600 text-xs">Alpha Miner 模型訓練後會自動產生</p>
                    </div>
                )}

                {/* Signal cards */}
                {!loading && signals.length > 0 && (
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                        {signals.map(s => {
                            const isExpanded = expandedId === s.stock_id
                            const isTop = s.trigger_count >= 20
                            const isMid = s.trigger_count >= 10 && s.trigger_count < 20

                            return (
                                <div
                                    key={s.stock_id}
                                    onClick={() => setExpandedId(isExpanded ? null : s.stock_id)}
                                    className={`
                                        rounded-2xl border p-4 cursor-pointer transition-all duration-200 select-none
                                        ${isTop
                                            ? 'bg-amber-500/5 border-amber-500/25 hover:border-amber-500/50 active:bg-amber-500/10'
                                            : isMid
                                                ? 'bg-emerald-500/5 border-emerald-500/20 hover:border-emerald-500/40 active:bg-emerald-500/10'
                                                : 'bg-zinc-800/20 border-zinc-800 hover:border-zinc-700 active:bg-zinc-800/40'}
                                        ${isExpanded ? (isTop ? 'border-amber-500/50' : isMid ? 'border-emerald-500/40' : 'border-zinc-700') : ''}
                                    `}
                                >
                                    {/* Card header */}
                                    <div className="flex items-start justify-between gap-2 mb-3">
                                        <div className="flex items-center gap-2 min-w-0">
                                            <div className="min-w-0">
                                                <p className="text-zinc-100 font-semibold text-sm leading-tight truncate">
                                                    {s.stock_name}
                                                </p>
                                                <p className="text-zinc-500 text-xs font-mono mt-0.5">{s.stock_id}</p>
                                            </div>
                                        </div>
                                        <TriggerBadge count={s.trigger_count} />
                                    </div>

                                    {/* Strategy preview (collapsed: first 3, expanded: all) */}
                                    <div className="flex flex-wrap gap-1.5">
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

                                    {/* Expanded action */}
                                    {isExpanded && (
                                        <div
                                            className="mt-3 pt-3 border-t border-zinc-700/50 flex justify-between items-center"
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

                {/* Disclaimer */}
                {!loading && signals.length > 0 && (
                    <p className="text-zinc-600 text-xs text-center pb-2">
                        AlphaForge 為學習型工具，訊號為歷史統計參考，不構成投資建議。
                    </p>
                )}
            </div>
        </>
    )
}
