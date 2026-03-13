import React, { useEffect, useState } from 'react'
import Head from 'next/head'
import api from '../lib/api'
import {
    LineChart, Line, XAxis, YAxis, Tooltip,
    ResponsiveContainer, CartesianGrid, ReferenceLine
} from 'recharts'

// ─── Types ────────────────────────────────────────────────────────────────────
interface EquityCurvePoint { date: string; cumulative_return: number }
interface RecentSignal {
    stock_id: string; stock_name: string; signal_date: string
    return_1d: number | null; return_10d: number | null
    outcome: 'win' | 'loss' | 'pending'
}
interface AlphaStats {
    strategy_id: string; strategy_name: string
    win_rate_1d: number; win_rate_10d: number
    expectancy: number; total_signals: number
    equity_curve: EquityCurvePoint[]
    recent_signals: RecentSignal[]
    data_date: string
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
const pct = (v: number | null, decimals = 1) =>
    v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(decimals)}%`

const SVGIcon = ({ path, className = 'w-5 h-5' }: { path: string; className?: string }) => (
    <svg viewBox="0 0 24 24" className={`fill-current ${className}`}><path d={path} /></svg>
)

const ICONS = {
    strategy: 'M16,6L18.29,8.29L13.42,13.17L9.42,9.17L2,16.59L3.41,18L9.42,12L13.42,16L19.71,9.71L22,12V6H16Z',
    signal: 'M13,2.05V4.05C17.39,4.59 20.5,8.58 19.96,12.97C19.5,16.61 16.64,19.5 13,19.93V21.93C18.5,21.38 22.5,16.5 21.95,11C21.5,6.25 17.73,2.5 13,2.05M11,2.06C9.05,2.25 7.19,3 5.67,4.26L7.1,5.74C8.22,4.84 9.57,4.26 11,4.06V2.06M4.26,5.67C3,7.19 2.25,9.04 2.05,11H4.05C4.24,9.58 4.8,8.23 5.69,7.1L4.26,5.67M2.06,13C2.26,14.96 3.03,16.81 4.27,18.33L5.69,16.9C4.81,15.77 4.24,14.42 4.06,13H2.06M7.1,18.37L5.67,19.74C7.18,21 9.04,21.79 11,22V20C9.58,19.82 8.23,19.25 7.1,18.37Z',
    chart: 'M19,3H5C3.89,3 3,3.9 3,5V19C3,20.1 3.89,21 5,21H19C20.1,21 21,20.1 21,19V5C21,3.9 20.1,3 19,3M9,17H7V10H9V17M13,17H11V7H13V17M17,17H15V13H17V17Z',
    win: 'M20,12A8,8 0 0,1 12,20A8,8 0 0,1 4,12A8,8 0 0,1 12,4C12.76,4 13.5,4.11 14.2,4.31L15.77,2.74C14.61,2.26 13.34,2 12,2A10,10 0 0,0 2,12A10,10 0 0,0 12,22A10,10 0 0,0 22,12M7.91,10.08L6.5,11.5L11,16L21,6L19.59,4.58L11,13.17L7.91,10.08Z',
    pending: 'M12,2A10,10 0 0,0 2,12A10,10 0 0,0 12,22A10,10 0 0,0 22,12A10,10 0 0,0 12,2M12,20A8,8 0 0,1 4,12A8,8 0 0,1 12,4A8,8 0 0,1 20,12A8,8 0 0,1 12,20M12.5,7V12.25L17,14.92L16.25,16.15L11,13V7H12.5Z',
}

// ─── Custom Tooltip for equity curve ─────────────────────────────────────────
const CurveTooltip = ({ active, payload, label }: any) => {
    if (!active || !payload?.length) return null
    const val: number = payload[0].value
    return (
        <div className="bg-zinc-900 border border-zinc-700 rounded-xl px-3 py-2 text-xs shadow-xl">
            <p className="text-zinc-400 mb-1">{label}</p>
            <p className={val >= 0 ? 'text-emerald-400 font-bold' : 'text-rose-400 font-bold'}>
                累積損益：{pct(val * 100)}
            </p>
            <p className="text-zinc-500 text-xs mt-0.5">等權不複利累加</p>
        </div>
    )
}

// ─── Skeleton ─────────────────────────────────────────────────────────────────
const Skeleton = ({ className = '' }: { className?: string }) => (
    <div className={`animate-pulse bg-zinc-800/60 rounded-xl ${className}`} />
)

// ─── Main Page ────────────────────────────────────────────────────────────────
const StrategyPage = () => {
    const [stats, setStats] = useState<AlphaStats | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)

    useEffect(() => {
        api.get('/market/alpha/stats')
            .then(res => { setStats(res.data); setLoading(false) })
            .catch(e => { setError(e.message); setLoading(false) })
    }, [])

    const metricCards = stats ? [
        {
            label: '明日上漲機率', value: `${(stats.win_rate_1d * 100).toFixed(1)}%`,
            sub: '次日收正報酬勝率', color: 'text-amber-400'
        },
        {
            label: '兩週後勝率', value: `${(stats.win_rate_10d * 100).toFixed(1)}%`,
            sub: '10 交易日後勝率', color: 'text-amber-400'
        },
        {
            label: '期望報酬', value: pct(stats.expectancy * 100),
            sub: '單筆平均期望值', color: stats.expectancy >= 0 ? 'text-emerald-400' : 'text-rose-400'
        },
        {
            label: '累積訊號', value: stats.total_signals.toLocaleString(),
            sub: `歷史觸發次數`, color: 'text-zinc-200'
        },
    ] : []

    const curveData = stats?.equity_curve.map(p => ({
        date: p.date.slice(0, 7),  // YYYY-MM
        value: p.cumulative_return,
    })) ?? []

    return (
        <>
            <Head><title>策略開發 | AlphaForge</title></Head>

            <div className="min-h-[calc(100vh-64px)] p-4 sm:p-8 flex flex-col gap-6 max-w-7xl mx-auto">

                {/* Header */}
                <div className="relative overflow-hidden bg-zinc-900/30 border border-zinc-800/50 rounded-3xl p-6 sm:p-8 group">
                    <div className="absolute top-0 right-0 w-64 h-64 bg-emerald-500/5 rounded-full blur-3xl -mr-32 -mt-32 transition-colors group-hover:bg-emerald-500/10" />
                    <div className="relative flex flex-col md:flex-row md:items-center justify-between gap-6">
                        <div>
                            <div className="flex items-center gap-3">
                                <div className="p-2 bg-emerald-500/10 rounded-xl border border-emerald-500/20">
                                    <SVGIcon path={ICONS.strategy} className="w-6 h-6 text-emerald-400" />
                                </div>
                                <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-white">
                                    Alpha Miner <span className="bg-gradient-to-r from-amber-400 to-yellow-500 bg-clip-text text-transparent">策略金鑰</span>挖礦機
                                </h1>
                            </div>
                            <p className="text-zinc-400 text-sm mt-2 pl-1 border-l-2 border-amber-500/30">
                                {stats
                                    ? `基於 ${stats.total_signals.toLocaleString()} 個歷史訊號 · 數據截至 ${stats.data_date}`
                                    : loading ? '計算中…' : 'AF 精選策略歷史勝率分析'}
                            </p>
                        </div>
                        <div className="flex items-center self-start md:self-center">
                            <div className="px-4 py-2 bg-zinc-950 border border-zinc-800 rounded-2xl flex items-center gap-3 shadow-xl">
                                <span className="relative flex h-2 w-2">
                                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75" />
                                    <span className="relative inline-flex rounded-full h-2 w-2 bg-amber-500" />
                                </span>
                                <span className="text-zinc-300 text-xs font-bold tracking-widest uppercase">AF 精選 · Phase 2</span>
                            </div>
                        </div>
                    </div>
                </div>

                {/* Error State */}
                {error && (
                    <div className="bg-rose-900/20 border border-rose-800/50 rounded-2xl p-4 text-rose-400 text-sm">
                        載入失敗：{error}
                    </div>
                )}

                {/* Metric Cards */}
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                    {loading
                        ? Array(4).fill(0).map((_, i) => <Skeleton key={i} className="h-28" />)
                        : metricCards.map((card, i) => (
                            <div key={i} className="bg-zinc-900/50 border border-zinc-800 rounded-2xl p-5 flex flex-col gap-2">
                                <p className="text-zinc-500 text-xs font-bold uppercase tracking-widest">{card.label}</p>
                                <p className={`text-3xl font-extrabold ${card.color}`}>{card.value}</p>
                                <p className="text-zinc-600 text-xs">{card.sub}</p>
                            </div>
                        ))
                    }
                </div>

                {/* Equity Curve */}
                <div className="bg-zinc-900/50 border border-zinc-800 rounded-2xl p-5">
                    <h3 className="text-zinc-400 text-xs font-bold uppercase tracking-widest mb-4 flex items-center gap-2">
                        <SVGIcon path={ICONS.chart} className="w-4 h-4 text-amber-400" />
                        超賣反彈 · 累積損益曲線（10 交易日持有，等權不複利）
                    </h3>
                    {loading ? (
                        <Skeleton className="h-64 w-full" />
                    ) : curveData.length === 0 ? (
                        <div className="h-48 flex items-center justify-center text-zinc-600 text-sm">尚無足夠數據</div>
                    ) : (
                        <ResponsiveContainer width="100%" height={250}>
                            <LineChart data={curveData} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
                                <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                                <XAxis
                                    dataKey="date"
                                    tick={{ fill: '#71717a', fontSize: 10 }}
                                    tickLine={false}
                                    interval="preserveStartEnd"
                                />
                                <YAxis
                                    tickFormatter={v => `${(v * 100).toFixed(0)}%`}
                                    tick={{ fill: '#71717a', fontSize: 10 }}
                                    tickLine={false}
                                    axisLine={false}
                                    width={48}
                                />
                                <Tooltip content={<CurveTooltip />} />
                                <ReferenceLine y={0} stroke="#52525b" strokeDasharray="4 2" />
                                <Line
                                    type="monotone"
                                    dataKey="value"
                                    stroke="#f59e0b"
                                    strokeWidth={2}
                                    dot={false}
                                    activeDot={{ r: 4, fill: '#f59e0b' }}
                                />
                            </LineChart>
                        </ResponsiveContainer>
                    )}
                </div>

                {/* Recent Signals */}
                <div className="bg-zinc-900/50 border border-zinc-800 rounded-2xl p-5">
                    <h3 className="text-zinc-400 text-xs font-bold uppercase tracking-widest mb-4 flex items-center gap-2">
                        <SVGIcon path={ICONS.signal} className="w-4 h-4 text-amber-400" />
                        近期訊號（最新 10 筆）
                    </h3>
                    {loading ? (
                        <div className="space-y-3">
                            {Array(5).fill(0).map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}
                        </div>
                    ) : !stats?.recent_signals.length ? (
                        <div className="h-24 flex items-center justify-center text-zinc-600 text-sm">尚無訊號</div>
                    ) : (
                        <div className="overflow-x-auto">
                            <table className="w-full text-sm">
                                <thead>
                                    <tr className="text-zinc-500 text-xs uppercase tracking-widest border-b border-zinc-800">
                                        <th className="text-left py-2 pr-4">股票</th>
                                        <th className="text-left py-2 pr-4">訊號日</th>
                                        <th className="text-right py-2 pr-4">次日報酬</th>
                                        <th className="text-right py-2 pr-4">兩週報酬</th>
                                        <th className="text-center py-2">結果</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {stats.recent_signals.map((sig, i) => (
                                        <tr key={i} className="border-b border-zinc-800/50 hover:bg-zinc-800/20 transition-colors">
                                            <td className="py-2.5 pr-4">
                                                <span className="text-zinc-200 font-medium">{sig.stock_name}</span>
                                                <span className="text-zinc-500 text-xs ml-2">{sig.stock_id}</span>
                                            </td>
                                            <td className="py-2.5 pr-4 text-zinc-400 font-mono text-xs">{sig.signal_date}</td>
                                            <td className={`py-2.5 pr-4 text-right font-mono font-medium ${sig.return_1d == null ? 'text-zinc-600' : sig.return_1d >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                                                {pct(sig.return_1d)}
                                            </td>
                                            <td className={`py-2.5 pr-4 text-right font-mono font-medium ${sig.return_10d == null ? 'text-zinc-600' : sig.return_10d >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                                                {pct(sig.return_10d)}
                                            </td>
                                            <td className="py-2.5 text-center">
                                                {sig.outcome === 'win' && (
                                                    <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-emerald-500/10 text-emerald-400 rounded-full text-xs font-bold">
                                                        <SVGIcon path={ICONS.win} className="w-3 h-3" />勝
                                                    </span>
                                                )}
                                                {sig.outcome === 'loss' && (
                                                    <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-rose-500/10 text-rose-400 rounded-full text-xs font-bold">敗</span>
                                                )}
                                                {sig.outcome === 'pending' && (
                                                    <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-zinc-800 text-zinc-500 rounded-full text-xs">
                                                        <SVGIcon path={ICONS.pending} className="w-3 h-3" />持倉中
                                                    </span>
                                                )}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>

            </div>

            <style jsx>{`
                @keyframes shimmer { 100% { transform: translateX(100%); } }
            `}</style>
        </>
    )
}

export default StrategyPage
