import React, { useEffect, useState } from 'react'
import Head from 'next/head'
import Link from 'next/link'
import api from '../lib/api'
import { todayLabel } from '../lib/formatters'
import { useWatchlist } from '../lib/useWatchlist'

// ─── 推薦清單類型 ─────────────────────────────────────────────────

interface RecommendationPick {
    rank: number
    stock_id: string
    stock_name: string
    score: number
    trigger_factors: string[]
    is_stable: boolean
}

interface DimensionRecommendation {
    dimension: string
    forward_days: number
    signal_date: string
    long_picks: RecommendationPick[]
    long_win_rate: number
    long_avg_return: number
    short_picks: RecommendationPick[]
    short_win_rate: number
    short_avg_return: number
    ic: number
    is_significant: boolean
    confidence: 'high' | 'medium' | 'low'
}

interface RecommendationTable {
    dimensions: DimensionRecommendation[]
    last_trained: string
    train_period: string
    test_period: string
}

const CONFIDENCE_STYLE: Record<string, { bg: string; text: string; label: string }> = {
    high:   { bg: 'bg-amber-500/10 border-amber-500/30', text: 'text-amber-400', label: '高' },
    medium: { bg: 'bg-zinc-700/30 border-zinc-600/30',   text: 'text-zinc-300',  label: '中' },
    low:    { bg: 'bg-zinc-800/30 border-zinc-700/30',   text: 'text-zinc-500',  label: '低' },
}

const DIM_LABELS: Record<string, string> = { '20d': '20日' }

function PickRow({ pick, direction }: { pick: RecommendationPick; direction: 'long' | 'short' }) {
    const isLong = direction === 'long'
    return (
        <tr className="border-b border-zinc-800/30 hover:bg-zinc-800/20 transition-colors">
            <td className="py-2 pr-2 text-zinc-500 text-xs w-6">{pick.rank}</td>
            <td className="py-2 pr-2">
                <Link href={`/stock/${pick.stock_id}`} className="flex items-center gap-1.5 group">
                    <span className="text-zinc-200 text-xs font-semibold group-hover:text-amber-400 transition-colors">
                        {pick.stock_id}
                    </span>
                    <span className="text-zinc-500 text-xs truncate max-w-[5rem]">{pick.stock_name}</span>
                    {pick.is_stable && (
                        <span className="text-[10px] px-1 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20 shrink-0">穩定</span>
                    )}
                </Link>
            </td>
            <td className="py-2 text-right">
                <div className="flex flex-wrap justify-end gap-0.5">
                    {pick.trigger_factors.slice(0, 2).map((f, i) => (
                        <span key={i} className={`text-[10px] px-1 py-0.5 rounded ${
                            isLong ? 'bg-rose-500/10 text-rose-400' : 'bg-emerald-500/10 text-emerald-400'
                        }`}>{f}</span>
                    ))}
                </div>
            </td>
        </tr>
    )
}

function DimensionCard({ dim }: { dim: DimensionRecommendation }) {
    const conf = CONFIDENCE_STYLE[dim.confidence] ?? CONFIDENCE_STYLE.low
    const label = DIM_LABELS[dim.dimension] ?? dim.dimension

    return (
        <div className="bg-zinc-900/40 border border-zinc-800/60 rounded-2xl overflow-hidden">
            {/* Header */}
            <div className="px-4 py-3 border-b border-zinc-800/40 flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <span className="text-zinc-200 font-bold text-sm">{label}</span>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded-full border ${conf.bg} ${conf.text}`}>
                        IC {dim.ic > 0 ? '+' : ''}{(dim.ic * 100).toFixed(1)} · 信心{conf.label}
                    </span>
                </div>
                <span className="text-zinc-600 text-[10px] font-mono">{dim.signal_date}</span>
            </div>

            <div className="grid grid-cols-2 divide-x divide-zinc-800/40">
                {/* 看漲 */}
                <div className="p-3">
                    <div className="flex items-center justify-between mb-2">
                        <span className="text-rose-400 text-xs font-semibold flex items-center gap-1">
                            <svg viewBox="0 0 24 24" width={12} height={12} className="fill-current">
                                <path d="M16,6L18.29,8.29L13.42,13.17L9.42,9.17L2,16.59L3.41,18L9.42,12L13.42,16L19.71,9.71L22,12V6H16Z" />
                            </svg>
                            看漲 Top 5
                        </span>
                        <span className="text-zinc-500 text-[10px]">
                            WR {dim.long_win_rate.toFixed(0)}% · {dim.long_avg_return >= 0 ? '+' : ''}{dim.long_avg_return.toFixed(1)}%
                        </span>
                    </div>
                    <table className="w-full">
                        <tbody>
                            {dim.long_picks.map(p => <PickRow key={p.stock_id} pick={p} direction="long" />)}
                            {dim.long_picks.length === 0 && (
                                <tr><td colSpan={3} className="py-4 text-center text-zinc-600 text-xs">訓練中</td></tr>
                            )}
                        </tbody>
                    </table>
                </div>

                {/* 看跌 */}
                <div className="p-3">
                    <div className="flex items-center justify-between mb-2">
                        <span className="text-emerald-400 text-xs font-semibold flex items-center gap-1">
                            <svg viewBox="0 0 24 24" width={12} height={12} className="fill-current">
                                <path d="M16,18L18.29,15.71L13.42,10.83L9.42,14.83L2,7.41L3.41,6L9.42,12L13.42,8L19.71,14.29L22,12V18H16Z" />
                            </svg>
                            看跌 Top 5
                        </span>
                        <span className="text-zinc-500 text-[10px]">
                            WR {dim.short_win_rate.toFixed(0)}% · {dim.short_avg_return >= 0 ? '+' : ''}{dim.short_avg_return.toFixed(1)}%
                        </span>
                    </div>
                    <table className="w-full">
                        <tbody>
                            {dim.short_picks.map(p => <PickRow key={p.stock_id} pick={p} direction="short" />)}
                            {dim.short_picks.length === 0 && (
                                <tr><td colSpan={3} className="py-4 text-center text-zinc-600 text-xs">訓練中</td></tr>
                            )}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    )
}

function RecommendationSection({ data }: { data: RecommendationTable | null }) {
    if (!data || data.dimensions.length === 0) {
        return (
            <div className="bg-zinc-900/40 border border-zinc-800/60 rounded-2xl p-6 text-center">
                <p className="text-zinc-500 text-sm">推薦清單產生中，請稍候...</p>
                <p className="text-zinc-600 text-xs mt-1">模型每日 17:30 重新訓練</p>
            </div>
        )
    }

    return (
        <div className="space-y-3">
            <div className="flex items-center justify-between px-1">
                <div className="flex items-center gap-2">
                    <svg viewBox="0 0 24 24" width={16} height={16} className="fill-amber-400 shrink-0">
                        <path d="M12,17.27L18.18,21L16.54,13.97L22,9.24L14.81,8.62L12,2L9.19,8.62L2,9.24L7.45,13.97L5.82,21L12,17.27Z" />
                    </svg>
                    <h2 className="text-zinc-200 text-sm font-bold">每日推薦清單</h2>
                </div>
                <span className="text-zinc-600 text-[10px]">
                    訓練期 {data.train_period} · 測試期 {data.test_period}
                </span>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
                {data.dimensions.map(dim => (
                    <DimensionCard key={dim.dimension} dim={dim} />
                ))}
            </div>

            <p className="text-zinc-600 text-[10px] px-1 leading-relaxed">
                WR = 歷史勝率（做多=正報酬比例，做空=負報酬比例）。報酬為 Top/Bot 20% 平均報酬。
                看漲看跌各顯示模型分數最高/最低的 5 檔。以上為量化模型回測結果，非投資建議。
            </p>
        </div>
    )
}

// ─── 原有類型 ─────────────────────────────────────────────────────

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
    is_stable: boolean
}

type DimKey = '20d'
const DIM_CONFIG: Record<DimKey, { label: string; shortLabel: string; desc: string }> = {
    '20d': { label: '20日持有', shortLabel: '20日', desc: '門檻 3% / 5%' },
}

const toPct = (v: number) => `${(v * 100).toFixed(1)}%`
const oddsColor = (v: number) =>
    v >= 1.2 ? 'text-amber-400' : v >= 1.0 ? 'text-zinc-200' : 'text-rose-400'

const Skeleton = ({ className = '' }: { className?: string }) => (
    <div className={`animate-pulse bg-zinc-800/60 rounded-xl ${className}`} />
)

// 動態門檻：依 maxCount（有效策略數）的百分比決定等級
const TriggerBadge = ({ count, maxCount }: { count: number; maxCount: number }) => {
    const ratio = maxCount > 0 ? count / maxCount : 0
    if (ratio >= 0.7) return (
        <span className="px-2.5 py-1 rounded-full text-xs font-normal bg-amber-500/20 text-amber-400 border border-amber-500/30 shrink-0">
            超強共鳴
        </span>
    )
    if (ratio >= 0.4) return (
        <span className="px-2.5 py-1 rounded-full text-xs font-normal bg-emerald-500/15 text-emerald-400 border border-emerald-500/25 shrink-0">
            強共鳴
        </span>
    )
    return (
        <span className="px-2.5 py-1 rounded-full text-xs font-normal bg-zinc-700 text-zinc-300 border border-zinc-600 shrink-0">
            {count} 策略共鳴
        </span>
    )
}

interface SignalHistoryItem {
    signal_date: string
    stock_id: string
    stock_name: string
    time_dimension: string
    trigger_count: number
    weighted_win_rate: number
    weighted_odds_ratio: number
    actual_return: number | null
    is_resolved: boolean
}

interface StrategyItem { time_dimension: string; is_significant: boolean; ic: number }

// 模型健康警示 banner
const ModelHealthBanner = ({ posIc, totalSig }: { posIc: number; totalSig: number }) => {
    if (totalSig === 0) return null
    const ratio = posIc / totalSig
    if (ratio >= 0.5) return null  // 健康，不顯示
    const pct = Math.round(ratio * 100)
    const level = ratio < 0.2 ? 'critical' : 'warn'
    return (
        <div className={`flex gap-3 items-start rounded-2xl border px-4 py-3 text-sm ${
            level === 'critical'
                ? 'bg-rose-900/15 border-rose-800/40 text-rose-300'
                : 'bg-amber-900/15 border-amber-800/40 text-amber-300'
        }`}>
            <svg viewBox="0 0 24 24" width={18} height={18} className="shrink-0 mt-0.5 fill-current opacity-80">
                <path d="M13,14H11V10H13M13,18H11V16H13M1,21H23L12,2L1,21Z" />
            </svg>
            <div>
                <p className="font-semibold mb-0.5">近期市場環境警示</p>
                <p className="text-xs opacity-80 leading-relaxed">
                    本維度共 {totalSig} 個顯著策略，但只有 {posIc} 個（{pct}%）在測試期表現正向。
                    其餘策略的預測方向與實際報酬相反，代表近期市場環境可能已與訓練期有所不同。
                    訊號僅供參考，<strong>請務必自行判斷</strong>。
                </p>
            </div>
        </div>
    )
}

// ── 近期訊號表現元件 ──────────────────────────────────────────────────────────
interface DayGroup {
    date: string
    items: SignalHistoryItem[]
    resolved: SignalHistoryItem[]
    hitCount: number   // actual_return > threshold_low
}

const HISTORY_THR: Record<DimKey, number> = { '20d': 0.03 }

function SignalHistorySection({ history, dim }: { history: SignalHistoryItem[]; dim: DimKey }) {
    if (history.length === 0) return null

    // 按日期分組
    const byDate = history.reduce<Record<string, SignalHistoryItem[]>>((acc, r) => {
        ;(acc[r.signal_date] ??= []).push(r)
        return acc
    }, {})

    const thr = HISTORY_THR[dim]
    const groups: DayGroup[] = Object.entries(byDate)
        .sort(([a], [b]) => b.localeCompare(a))
        .map(([d, items]) => {
            const resolved = items.filter(i => i.is_resolved)
            const hitCount = resolved.filter(i => (i.actual_return ?? 0) > thr).length
            return { date: d, items, resolved, hitCount }
        })

    // 只顯示有足夠已結算記錄的日期（≥3 筆）
    const hasStats = groups.some(g => g.resolved.length >= 3)

    return (
        <div className="bg-zinc-900/40 border border-zinc-800/60 rounded-2xl p-4 sm:p-6">
            <div className="flex items-center gap-2 mb-4">
                <svg viewBox="0 0 24 24" width={16} height={16} className="fill-zinc-400 shrink-0">
                    <path d="M19,3H5C3.89,3 3,3.89 3,5V19A2,2 0 0,0 5,21H19A2,2 0 0,0 21,19V5C21,3.89 20.1,3 19,3M17,13H13V17H11V13H7V11H11V7H13V11H17V13Z" />
                </svg>
                <h2 className="text-zinc-200 text-sm font-semibold">近期訊號表現</h2>
                {!hasStats && (
                    <span className="text-zinc-600 text-xs">（結算中，持有期未到）</span>
                )}
            </div>

            <div className="overflow-x-auto">
                <table className="w-full text-xs border-collapse">
                    <thead>
                        <tr className="text-zinc-500 border-b border-zinc-800">
                            <th className="text-left pb-2 pr-4 font-normal whitespace-nowrap">日期</th>
                            <th className="text-right pb-2 pr-4 font-normal whitespace-nowrap">發出訊號</th>
                            <th className="text-right pb-2 pr-4 font-normal whitespace-nowrap">已結算</th>
                            <th className="text-right pb-2 pr-4 font-normal whitespace-nowrap">命中率</th>
                            <th className="text-right pb-2 font-normal whitespace-nowrap">平均報酬</th>
                        </tr>
                    </thead>
                    <tbody>
                        {groups.map(g => {
                            const hitRate = g.resolved.length >= 3
                                ? g.hitCount / g.resolved.length
                                : null
                            const avgReturn = g.resolved.length >= 3
                                ? g.resolved.reduce((s, i) => s + (i.actual_return ?? 0), 0) / g.resolved.length
                                : null

                            return (
                                <tr key={g.date} className="border-b border-zinc-800/40 hover:bg-zinc-800/20">
                                    <td className="py-2 pr-4 text-zinc-400 font-mono whitespace-nowrap">{g.date}</td>
                                    <td className="py-2 pr-4 text-right text-zinc-300">{g.items.length}</td>
                                    <td className="py-2 pr-4 text-right">
                                        {g.resolved.length > 0
                                            ? <span className="text-zinc-300">{g.resolved.length}</span>
                                            : <span className="text-zinc-600">—</span>}
                                    </td>
                                    <td className="py-2 pr-4 text-right">
                                        {hitRate !== null
                                            ? <span className={hitRate >= 0.5 ? 'text-rose-400 font-semibold' : 'text-zinc-400 font-semibold'}>
                                                {(hitRate * 100).toFixed(0)}%
                                              </span>
                                            : <span className="text-zinc-600 text-[10px]">待觀察</span>}
                                    </td>
                                    <td className="py-2 text-right">
                                        {avgReturn !== null
                                            ? <span className={avgReturn >= 0 ? 'text-rose-400 font-mono' : 'text-emerald-400 font-mono'}>
                                                {avgReturn >= 0 ? '+' : ''}{(avgReturn * 100).toFixed(1)}%
                                              </span>
                                            : <span className="text-zinc-600 text-[10px]">待觀察</span>}
                                    </td>
                                </tr>
                            )
                        })}
                    </tbody>
                </table>
            </div>
            <p className="text-zinc-600 text-[10px] mt-3 leading-relaxed">
                命中率 = 持有期實際漲幅 &gt; {(thr * 100).toFixed(0)}%。結算需至少 3 筆記錄才顯示統計。
            </p>
        </div>
    )
}

export default function SignalsPage() {
    const [signals, setSignals] = useState<TodaySignal[]>([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [expandedId, setExpandedId] = useState<string | null>(null)
    const [dim, setDim] = useState<DimKey>('20d')
    const { toggle, has } = useWatchlist()
    const [dimStats, setDimStats] = useState<Record<DimKey, { posIc: number; totalSig: number }>>({
        '20d': { posIc: 0, totalSig: 0 },
    })
    const [history, setHistory] = useState<SignalHistoryItem[]>([])
    const [recommendations, setRecommendations] = useState<RecommendationTable | null>(null)

    // 一次性載入策略資料 + 推薦清單
    useEffect(() => {
        api.get('/alpha-miner/strategies').then(r => {
            const strats: StrategyItem[] = r.data?.strategies ?? []
            const stats = { '20d': { posIc: 0, totalSig: 0 } } as Record<DimKey, { posIc: number; totalSig: number }>
            strats.forEach(s => {
                const d = s.time_dimension as DimKey
                if (!stats[d] || !s.is_significant) return
                stats[d].totalSig++
                if (s.ic > 0) stats[d].posIc++
            })
            setDimStats(stats)
        }).catch(() => {})

        api.get('/alpha-miner/recommendations?top_n=5')
            .then(r => setRecommendations(r.data))
            .catch(() => {})
    }, [])

    useEffect(() => {
        setLoading(true)
        setError(null)
        api.get(`/alpha-miner/signals/today?dimension=${dim}`)
            .then(r => { setSignals(r.data); setLoading(false) })
            .catch(e => { setError(e.message); setLoading(false) })
        const historyDays = 45
        api.get(`/alpha-miner/signals/history?dimension=${dim}&days=${historyDays}`)
            .then(r => setHistory(r.data))
            .catch(() => {})
    }, [dim])

    const tlo = 3
    const thi = 5

    const signalDate = signals[0]?.signal_date ?? ''
    const maxPossibleTrigger = dimStats[dim].posIc  // 有效策略數 = 最大可能 trigger_count
    const topCount = signals.filter(s => maxPossibleTrigger > 0 && s.trigger_count / maxPossibleTrigger >= 0.7).length
    const midCount = signals.filter(s => maxPossibleTrigger > 0 && s.trigger_count / maxPossibleTrigger >= 0.4 && s.trigger_count / maxPossibleTrigger < 0.7).length

    return (
        <>
            <Head><title>{todayLabel()} 最強訊號 | AlphaForge</title></Head>
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
                                    {todayLabel()} 最強訊號
                                </h1>
                            </div>
                            <p className="text-zinc-500 text-sm sm:text-base mt-1.5 leading-relaxed">
                                {signalDate
                                    ? `${signalDate} · 多策略共鳴 · IC 加權歷史勝率`
                                    : loading ? '載入中…' : 'Alpha Miner 多因子訊號聚合'}
                            </p>
                        </div>
                        <Link
                            href="/strategy"
                            className="shrink-0 flex items-center gap-2 px-4 py-2.5 bg-rose-500/10 border border-rose-500/25 rounded-xl text-rose-400 hover:bg-rose-500/20 transition-colors text-sm font-semibold whitespace-nowrap"
                        >
                            <svg viewBox="0 0 24 24" width={16} height={16} className="fill-current">
                                <path d="M16,6L18.29,8.29L13.42,13.17L9.42,9.17L2,16.59L3.41,18L9.42,12L13.42,16L19.71,9.71L22,12V6H16Z" />
                            </svg>
                            {todayLabel()} 操作建議
                        </Link>

                    </div>
                </div>

                {/* ── Recommendation Table ────────────────────────────── */}
                <RecommendationSection data={recommendations} />

                {/* ── Model Health Banner ─────────────────────────────── */}
                <ModelHealthBanner posIc={dimStats[dim].posIc} totalSig={dimStats[dim].totalSig} />

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
                            <span className="text-zinc-500 text-xs">超強共鳴<span className="hidden sm:inline">（≥70%）</span></span>
                            <span className="text-zinc-700 text-xs">·</span>
                            <span className="text-emerald-400 font-bold text-xs">{midCount}</span>
                            <span className="text-zinc-500 text-xs">強共鳴<span className="hidden sm:inline">（40–69%）</span></span>
                            <span className="text-zinc-700 text-xs">·</span>
                            <span className="text-zinc-300 font-bold text-xs">{signals.length - topCount - midCount}</span>
                            <span className="text-zinc-500 text-xs">一般<span className="hidden sm:inline">（&lt;40%）</span></span>
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
                            {todayLabel()} 暫無訊號（Alpha Miner 模型訓練後自動產生）
                        </div>
                    )}

                    {/* Signal cards */}
                    {!loading && signals.length > 0 && (
                        <div className="space-y-2.5">
                            {signals.map(s => {
                                const isExpanded = expandedId === s.stock_id
                                const ratio = maxPossibleTrigger > 0 ? s.trigger_count / maxPossibleTrigger : 0
                                const isTop = ratio >= 0.7
                                const isMid = ratio >= 0.4 && ratio < 0.7

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
                                                    {s.is_stable && (
                                                        <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-cyan-900/40 text-cyan-400 border border-cyan-800/50">
                                                            穩定
                                                        </span>
                                                    )}
                                                    <span className="px-2.5 py-1 rounded-full text-xs font-normal bg-zinc-700/60 text-zinc-400 border border-zinc-700 shrink-0">
                                                        {DIM_CONFIG[dim].shortLabel}後
                                                    </span>
                                                    <TriggerBadge count={s.trigger_count} maxCount={maxPossibleTrigger} />
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
                                                        <span className={`text-base font-bold font-mono ${s.weighted_win_rate > s.weighted_market_win_rate ? 'text-rose-400' : 'text-emerald-400'}`}>
                                                            {toPct(s.weighted_win_rate)}
                                                        </span>
                                                    </div>
                                                    <div className="flex justify-between items-baseline">
                                                        <span className="text-zinc-400 text-xs">&lt;-{tlo}% 踩雷</span>
                                                        <span className={`text-base font-bold font-mono ${s.weighted_loss_rate < s.weighted_market_loss_rate ? 'text-rose-400' : 'text-emerald-400'}`}>
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
                                                        <span className={`text-base font-bold font-mono ${s.weighted_win_rate_hi > s.weighted_market_win_rate_hi ? 'text-rose-400' : 'text-emerald-400'}`}>
                                                            {toPct(s.weighted_win_rate_hi)}
                                                        </span>
                                                    </div>
                                                    <div className="flex justify-between items-baseline">
                                                        <span className="text-zinc-400 text-xs">&lt;-{thi}% 踩雷</span>
                                                        <span className={`text-base font-bold font-mono ${s.weighted_loss_rate_hi < s.weighted_market_loss_rate_hi ? 'text-rose-400' : 'text-emerald-400'}`}>
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
                                                className="px-4 pb-4 pt-3 border-t border-zinc-700/50 flex justify-between items-center gap-2"
                                                onClick={e => e.stopPropagation()}
                                            >
                                                <span className="text-zinc-600 text-xs">共 {s.strategies.length} 個策略觸發</span>
                                                <div className="flex items-center gap-2">
                                                    <button
                                                        onClick={() => toggle(s.stock_id, s.stock_name)}
                                                        title={has(s.stock_id) ? '從觀察清單移除' : '加入觀察清單'}
                                                        className={`p-1.5 rounded-lg border transition-colors ${
                                                            has(s.stock_id)
                                                                ? 'text-amber-400 border-amber-500/30 bg-amber-500/10'
                                                                : 'text-zinc-600 border-zinc-700 hover:text-amber-400 hover:border-amber-500/30'
                                                        }`}
                                                    >
                                                        <svg viewBox="0 0 24 24" width={14} height={14} className="fill-current">
                                                            <path d={has(s.stock_id)
                                                                ? "M12,17.27L18.18,21L16.54,13.97L22,9.24L14.81,8.62L12,2L9.19,8.62L2,9.24L7.45,13.97L5.82,21L12,17.27Z"
                                                                : "M12,15.39L8.24,17.66L9.23,13.38L5.91,10.5L10.29,10.13L12,6.09L13.71,10.13L18.09,10.5L14.77,13.38L15.76,17.66M22,9.24L14.81,8.62L12,2L9.19,8.62L2,9.24L7.45,13.97L5.82,21L12,17.27L18.18,21L16.54,13.97L22,9.24Z"
                                                            } />
                                                        </svg>
                                                    </button>
                                                    <Link
                                                        href={`/stock/${s.stock_id}`}
                                                        className="px-3 py-1.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs rounded-lg transition-colors font-medium"
                                                    >
                                                        查看個股 →
                                                    </Link>
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                )
                            })}
                        </div>
                    )}
                </div>

                {/* ── Signal History ──────────────────────────────────── */}
                <SignalHistorySection history={history} dim={dim} />

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
