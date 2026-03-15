import React, { useEffect, useState } from 'react'
import Head from 'next/head'
import api from '../lib/api'
import {
    LineChart, Line, XAxis, YAxis, Tooltip,
    ResponsiveContainer, CartesianGrid, ReferenceLine
} from 'recharts'

// ─── Types ────────────────────────────────────────────────────────────────────
interface FactorWeight { factor: string; factor_label: string; coefficient: number; direction: string }
interface EquityCurvePoint { date: string; cumulative_return: number }
interface RecentAlphaSignal {
    stock_id: string; stock_name: string; signal_date: string
    predicted_prob: number; trigger_factors: string[]
}
interface StrategyRanking {
    strategy_id: string; strategy_name: string; factors: string[]
    win_rate_insample: number; win_rate_outsample: number
    loss_rate_outsample: number; odds_ratio: number
    market_win_rate: number; market_loss_rate: number
    ic: number; p_value: number; p_value_corrected: number
    is_significant: boolean; overfit_warning: boolean
    sample_count_train: number; sample_count_test: number
    integrity_flags: string[]
}
interface StrategyDetail extends StrategyRanking {
    equity_curve: EquityCurvePoint[]
    recent_signals: RecentAlphaSignal[]
    factor_weights: FactorWeight[]
}
interface TodaySignal {
    stock_id: string; stock_name: string
    trigger_count: number; strategies: string[]; signal_date: string
}
interface AlphaMinerResult {
    strategies: StrategyRanking[]; last_trained: string
    train_period: string; test_period: string
    total_combinations_tested: number; bonferroni_threshold: number
    is_training: boolean
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
const pct = (v: number, d = 1) => `${v >= 0 ? '+' : ''}${(v * 100).toFixed(d)}%`
const Skeleton = ({ className = '' }: { className?: string }) => (
    <div className={`animate-pulse bg-zinc-800/60 rounded-xl ${className}`} />
)
const CurveTooltip = ({ active, payload, label }: any) => {
    if (!active || !payload?.length) return null
    const val: number = payload[0].value
    return (
        <div className="bg-zinc-900 border border-zinc-700 rounded-xl px-3 py-2 text-xs shadow-xl">
            <p className="text-zinc-400 mb-1">{label}</p>
            <p className={val >= 0 ? 'text-emerald-400 font-bold' : 'text-rose-400 font-bold'}>
                累積損益：{pct(val)}
            </p>
        </div>
    )
}

// ─── Strategy Detail Panel ────────────────────────────────────────────────────
const DetailPanel = ({ strategyId, onClose }: { strategyId: string; onClose: () => void }) => {
    const [detail, setDetail] = useState<StrategyDetail | null>(null)
    const [loading, setLoading] = useState(true)

    useEffect(() => {
        setLoading(true)
        api.get(`/alpha-miner/strategies/${strategyId}`)
            .then(r => { setDetail(r.data); setLoading(false) })
            .catch(() => setLoading(false))
    }, [strategyId])

    const maxCoef = detail ? Math.max(...detail.factor_weights.map(w => Math.abs(w.coefficient)), 0.01) : 1

    return (
        <div className="bg-zinc-900/70 border border-zinc-700 rounded-2xl p-5 space-y-5">
            <div className="flex items-center justify-between">
                <h3 className="text-white font-bold">{detail?.strategy_name ?? '…'}</h3>
                <button onClick={onClose} className="text-zinc-500 hover:text-zinc-300 text-xs px-3 py-1 rounded-lg border border-zinc-700 hover:border-zinc-500 transition-colors">
                    收起
                </button>
            </div>

            {loading ? (
                <div className="space-y-3">{Array(3).fill(0).map((_, i) => <Skeleton key={i} className="h-16" />)}</div>
            ) : !detail ? (
                <p className="text-zinc-500 text-sm">載入失敗</p>
            ) : (
                <>
                    {/* Integrity flags */}
                    {detail.integrity_flags.length > 0 && (
                        <div className="flex flex-wrap gap-2">
                            {detail.integrity_flags.map((flag, i) => (
                                <span key={i} className="px-2 py-0.5 bg-amber-500/10 border border-amber-500/30 text-amber-400 rounded-full text-xs">{flag}</span>
                            ))}
                        </div>
                    )}

                    {/* Metric comparison */}
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                        {[
                            { label: '勝率 >3%（策略）', value: `${(detail.win_rate_outsample * 100).toFixed(1)}%`, color: detail.win_rate_outsample > detail.market_win_rate ? 'text-emerald-400' : 'text-rose-400' },
                            { label: '勝率 >3%（市場基準）', value: `${(detail.market_win_rate * 100).toFixed(1)}%`, color: 'text-zinc-400' },
                            { label: '踩雷率 <-3%（策略）', value: `${(detail.loss_rate_outsample * 100).toFixed(1)}%`, color: detail.loss_rate_outsample < detail.market_loss_rate ? 'text-emerald-400' : 'text-rose-400' },
                            { label: '踩雷率 <-3%（市場基準）', value: `${(detail.market_loss_rate * 100).toFixed(1)}%`, color: 'text-zinc-400' },
                            { label: '賠率比', value: detail.odds_ratio.toFixed(2), color: detail.odds_ratio >= 1.2 ? 'text-amber-400' : detail.odds_ratio >= 1.0 ? 'text-zinc-300' : 'text-rose-400' },
                            { label: 'IC', value: detail.ic.toFixed(3), color: detail.ic > 0 ? 'text-amber-400' : 'text-zinc-400' },
                            { label: '測試訊號數', value: detail.sample_count_test.toLocaleString(), color: 'text-zinc-300' },
                        ].map((m, i) => (
                            <div key={i} className="bg-zinc-800/50 rounded-xl p-3 text-center">
                                <p className="text-zinc-500 text-xs mb-1">{m.label}</p>
                                <p className={`text-xl font-bold ${m.color}`}>{m.value}</p>
                            </div>
                        ))}
                    </div>

                    {/* Factor weights */}
                    <div>
                        <p className="text-zinc-500 text-xs uppercase tracking-widest mb-3">因子權重係數</p>
                        <div className="space-y-2">
                            {detail.factor_weights.map((fw, i) => (
                                <div key={i} className="flex items-center gap-3">
                                    <span className="text-zinc-400 text-xs w-20 text-right shrink-0">{fw.factor_label}</span>
                                    <div className="flex-1 bg-zinc-800 rounded-full h-2">
                                        <div
                                            className={`h-2 rounded-full ${fw.direction === 'bullish' ? 'bg-emerald-500' : 'bg-rose-500'}`}
                                            style={{ width: `${Math.abs(fw.coefficient) / maxCoef * 100}%` }}
                                        />
                                    </div>
                                    <span className={`text-xs font-mono w-14 shrink-0 ${fw.direction === 'bullish' ? 'text-emerald-400' : 'text-rose-400'}`}>
                                        {fw.coefficient > 0 ? '+' : ''}{fw.coefficient.toFixed(2)}
                                    </span>
                                </div>
                            ))}
                        </div>
                    </div>

                    {/* Equity curve */}
                    {detail.equity_curve.length > 1 && (
                        <div>
                            <p className="text-zinc-500 text-xs uppercase tracking-widest mb-3">測試集累積損益（等權不複利）</p>
                            <ResponsiveContainer width="100%" height={180}>
                                <LineChart data={detail.equity_curve.map(p => ({ date: p.date, value: p.cumulative_return }))} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
                                    <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                                    <XAxis dataKey="date" tick={{ fill: '#71717a', fontSize: 9 }} tickLine={false} interval="preserveStartEnd" />
                                    <YAxis tickFormatter={v => pct(v, 0)} tick={{ fill: '#71717a', fontSize: 9 }} tickLine={false} axisLine={false} width={44} />
                                    <Tooltip content={<CurveTooltip />} />
                                    <ReferenceLine y={0} stroke="#52525b" strokeDasharray="4 2" />
                                    <Line type="monotone" dataKey="value" stroke="#f59e0b" strokeWidth={2} dot={false} activeDot={{ r: 3, fill: '#f59e0b' }} />
                                </LineChart>
                            </ResponsiveContainer>
                        </div>
                    )}

                    {/* Recent signals */}
                    {detail.recent_signals.length > 0 && (
                        <div>
                            <p className="text-zinc-500 text-xs uppercase tracking-widest mb-3">近期訊號（最新交易日）</p>
                            <div className="flex flex-wrap gap-2">
                                {detail.recent_signals.map((sig, i) => (
                                    <div key={i} className="bg-zinc-800/60 border border-zinc-700 rounded-xl px-3 py-2 text-xs">
                                        <span className="text-white font-medium">{sig.stock_name}</span>
                                        <span className="text-zinc-500 ml-1">{sig.stock_id}</span>
                                        <span className="text-amber-400 ml-2 font-mono">{(sig.predicted_prob * 100).toFixed(0)}%</span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                </>
            )}
        </div>
    )
}

// ─── Main Page ────────────────────────────────────────────────────────────────
const StrategyPage = () => {
    const [result, setResult] = useState<AlphaMinerResult | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [selectedId, setSelectedId] = useState<string | null>(null)
    const [signals, setSignals] = useState<TodaySignal[]>([])
    const [expandedSignal, setExpandedSignal] = useState<string | null>(null)

    useEffect(() => {
        let timer: ReturnType<typeof setTimeout>
        const fetch = () => {
            api.get('/alpha-miner/strategies')
                .then(r => {
                    setResult(r.data)
                    setLoading(false)
                    if (r.data.is_training) {
                        // 訓練中：15 秒後再輪詢
                        timer = setTimeout(fetch, 15000)
                    }
                })
                .catch(e => { setError(e.message); setLoading(false) })
        }
        fetch()
        return () => clearTimeout(timer)
    }, [])

    useEffect(() => {
        api.get('/alpha-miner/signals/today')
            .then(r => setSignals(r.data))
            .catch(() => {})
    }, [])

    const strategies = result?.strategies ?? []

    return (
        <>
            <Head><title>Alpha Miner | AlphaForge</title></Head>
            <div className="min-h-[calc(100vh-64px)] p-4 sm:p-8 flex flex-col gap-6 max-w-7xl mx-auto">

                {/* Header */}
                <div className="relative overflow-hidden bg-zinc-900/30 border border-zinc-800/50 rounded-3xl p-6 sm:p-8 group">
                    <div className="absolute top-0 right-0 w-64 h-64 bg-amber-500/5 rounded-full blur-3xl -mr-32 -mt-32" />
                    <div className="relative flex flex-col md:flex-row md:items-center justify-between gap-4">
                        <div>
                            <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-white">
                                Alpha Miner <span className="bg-gradient-to-r from-amber-400 to-yellow-500 bg-clip-text text-transparent">策略金鑰</span>挖礦機
                            </h1>
                            <p className="text-zinc-400 text-sm mt-2 pl-1 border-l-2 border-amber-500/30">
                                {result
                                    ? `${result.total_combinations_tested} 組因子組合 · 訓練期 ${result.train_period} · 測試期 ${result.test_period}`
                                    : result?.is_training ? '模型訓練中（約需 2 分鐘），頁面將自動更新…'
                        : loading ? '載入中…' : 'Alpha Miner 多因子邏輯迴歸模型'
                                }
                            </p>
                        </div>
                        <div className="flex items-center gap-3 shrink-0">
                            <div className="px-4 py-2 bg-zinc-950 border border-zinc-800 rounded-2xl flex items-center gap-2 shadow-xl">
                                <span className="relative flex h-2 w-2">
                                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75" />
                                    <span className="relative inline-flex rounded-full h-2 w-2 bg-amber-500" />
                                </span>
                                <span className="text-zinc-300 text-xs font-bold tracking-widest uppercase">Phase 5B</span>
                            </div>
                        </div>
                    </div>
                </div>

                {error && (
                    <div className="bg-rose-900/20 border border-rose-800/50 rounded-2xl p-4 text-rose-400 text-sm">
                        載入失敗：{error}
                    </div>
                )}

                {/* Today Signals */}
                {signals.length > 0 && (
                    <div className="bg-zinc-900/50 border border-zinc-800 rounded-2xl p-5">
                        <div className="flex items-baseline justify-between mb-4">
                            <h3 className="text-zinc-400 text-xs font-bold uppercase tracking-widest">今日最強訊號</h3>
                            <span className="text-zinc-600 text-xs">{signals[0]?.signal_date} · 僅供參考，不構成投資建議</span>
                        </div>
                        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
                            {signals.map(s => (
                                <div
                                    key={s.stock_id}
                                    onClick={() => setExpandedSignal(expandedSignal === s.stock_id ? null : s.stock_id)}
                                    className={`rounded-xl border px-4 py-3 cursor-pointer transition-colors ${expandedSignal === s.stock_id ? 'bg-zinc-800/60 border-zinc-600' : 'bg-zinc-800/20 border-zinc-800 hover:border-zinc-700'}`}
                                >
                                    <div className="flex items-center justify-between gap-2">
                                        <div className="flex items-center gap-2 min-w-0">
                                            <span className="text-zinc-200 font-medium truncate">{s.stock_name}</span>
                                            <span className="text-zinc-500 text-xs shrink-0">{s.stock_id}</span>
                                        </div>
                                        <span className={`shrink-0 px-2 py-0.5 rounded-full text-xs font-bold ${s.trigger_count >= 20 ? 'bg-amber-500/20 text-amber-400' : s.trigger_count >= 10 ? 'bg-emerald-500/15 text-emerald-400' : 'bg-zinc-700 text-zinc-300'}`}>
                                            {s.trigger_count} 策略
                                        </span>
                                    </div>
                                    {expandedSignal === s.stock_id && (
                                        <div className="mt-2 flex flex-wrap gap-1">
                                            {s.strategies.slice(0, 8).map((name, i) => (
                                                <span key={i} className="px-2 py-0.5 bg-zinc-700/60 text-zinc-400 rounded-full text-xs">{name}</span>
                                            ))}
                                            {s.strategies.length > 8 && (
                                                <span className="px-2 py-0.5 text-zinc-600 text-xs">+{s.strategies.length - 8} 個</span>
                                            )}
                                        </div>
                                    )}
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                {/* Strategy Ranking Table */}
                <div className="bg-zinc-900/50 border border-zinc-800 rounded-2xl p-5">
                    <div className="flex items-baseline justify-between mb-4">
                        <h3 className="text-zinc-400 text-xs font-bold uppercase tracking-widest">策略排行榜（依樣本外 IC 排序）</h3>
                        {strategies.length > 0 && (
                            <span className="hidden sm:inline text-zinc-600 text-xs">
                                市場基準：勝率 {((strategies[0]?.market_win_rate ?? 0) * 100).toFixed(1)}%・踩雷率 {((strategies[0]?.market_loss_rate ?? 0) * 100).toFixed(1)}%
                            </span>
                        )}
                    </div>

                    {loading ? (
                        <div className="space-y-3">{Array(6).fill(0).map((_, i) => <Skeleton key={i} className="h-16" />)}</div>
                    ) : strategies.length === 0 ? (
                        <div className="h-32 flex items-center justify-center text-zinc-500 text-sm">
                            {result?.is_training ? '模型訓練中，頁面每 15 秒自動更新…' : '尚無資料（stock_features 資料不足）'}
                        </div>
                    ) : (
                        <>
                            {/* ── 手機版：卡片列表 ─────────────────────────────── */}
                            <div className="md:hidden space-y-2">
                                {strategies.map((s, idx) => (
                                    <React.Fragment key={s.strategy_id}>
                                        <div
                                            onClick={() => setSelectedId(selectedId === s.strategy_id ? null : s.strategy_id)}
                                            className={`rounded-xl border px-4 py-3 cursor-pointer transition-colors ${selectedId === s.strategy_id ? 'bg-zinc-800/60 border-zinc-600' : 'bg-zinc-800/20 border-zinc-800 active:bg-zinc-800/50'}`}
                                        >
                                            {/* 第一行：排名 + 名稱 + 顯著badge */}
                                            <div className="flex items-start justify-between gap-2 mb-2">
                                                <div className="flex items-start gap-2">
                                                    <span className="text-zinc-500 text-xs font-mono mt-0.5 w-5 shrink-0">#{idx + 1}</span>
                                                    <span className="text-zinc-100 text-sm font-medium leading-snug">
                                                        {s.strategy_name}
                                                        {s.overfit_warning && <span className="ml-1 text-amber-500 text-xs">⚠</span>}
                                                    </span>
                                                </div>
                                                {s.is_significant
                                                    ? <span className="shrink-0 px-2 py-0.5 bg-emerald-500/10 text-emerald-600 rounded-full text-xs">顯著</span>
                                                    : <span className="shrink-0 px-2 py-0.5 bg-rose-500/10 text-rose-400 rounded-full text-xs">不顯著</span>
                                                }
                                            </div>
                                            {/* 第二行：三個指標 */}
                                            <div className="grid grid-cols-3 gap-1 pl-7">
                                                <div className="text-center">
                                                    <p className="text-zinc-400 text-[10px] mb-0.5">勝率&gt;3%</p>
                                                    <p className={`text-sm font-mono font-bold ${s.win_rate_outsample > s.market_win_rate ? 'text-emerald-400' : 'text-rose-400'}`}>
                                                        {(s.win_rate_outsample * 100).toFixed(1)}%
                                                    </p>
                                                </div>
                                                <div className="text-center">
                                                    <p className="text-zinc-400 text-[10px] mb-0.5">踩雷&lt;-3%</p>
                                                    <p className={`text-sm font-mono font-bold ${s.loss_rate_outsample < s.market_loss_rate ? 'text-emerald-400' : 'text-rose-400'}`}>
                                                        {(s.loss_rate_outsample * 100).toFixed(1)}%
                                                    </p>
                                                </div>
                                                <div className="text-center">
                                                    <p className="text-zinc-400 text-[10px] mb-0.5">賠率比</p>
                                                    <p className={`text-sm font-mono font-bold ${s.odds_ratio >= 1.2 ? 'text-amber-400' : s.odds_ratio >= 1.0 ? 'text-zinc-300' : 'text-rose-400'}`}>
                                                        {s.odds_ratio.toFixed(2)}x
                                                    </p>
                                                </div>
                                            </div>
                                        </div>
                                        {selectedId === s.strategy_id && (
                                            <div className="pb-1">
                                                <DetailPanel strategyId={s.strategy_id} onClose={() => setSelectedId(null)} />
                                            </div>
                                        )}
                                    </React.Fragment>
                                ))}
                            </div>

                            {/* ── 桌機版：表格 ─────────────────────────────────── */}
                            <div className="hidden md:block overflow-x-auto">
                                <table className="w-full text-sm">
                                    <thead>
                                        <tr className="text-zinc-500 text-xs uppercase tracking-widest border-b border-zinc-800">
                                            <th className="text-left py-2 pr-4 w-8">#</th>
                                            <th className="text-left py-2 pr-6">策略名稱</th>
                                            <th className="text-right py-2 pr-4">勝率 &gt;3%</th>
                                            <th className="text-right py-2 pr-4">踩雷 &lt;-3%</th>
                                            <th className="text-right py-2 pr-4">賠率比</th>
                                            <th className="text-right py-2 pr-4">IC</th>
                                            <th className="text-right py-2 pr-4">p-value</th>
                                            <th className="text-center py-2">狀態</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {strategies.map((s, idx) => (
                                            <React.Fragment key={s.strategy_id}>
                                                <tr
                                                    onClick={() => setSelectedId(selectedId === s.strategy_id ? null : s.strategy_id)}
                                                    className={`border-b border-zinc-800/50 cursor-pointer transition-colors ${selectedId === s.strategy_id ? 'bg-zinc-800/40' : 'hover:bg-zinc-800/20'}`}
                                                >
                                                    <td className="py-3 pr-4 text-zinc-600 font-mono text-xs">{idx + 1}</td>
                                                    <td className="py-3 pr-6">
                                                        <span className="text-zinc-200 font-medium">{s.strategy_name}</span>
                                                        {s.overfit_warning && <span className="ml-2 text-amber-500 text-xs">⚠</span>}
                                                    </td>
                                                    <td className={`py-3 pr-4 text-right font-mono font-medium ${s.win_rate_outsample > s.market_win_rate ? 'text-emerald-400' : 'text-rose-400'}`}>
                                                        {(s.win_rate_outsample * 100).toFixed(1)}%
                                                    </td>
                                                    <td className={`py-3 pr-4 text-right font-mono font-medium ${s.loss_rate_outsample < s.market_loss_rate ? 'text-emerald-400' : 'text-rose-400'}`}>
                                                        {(s.loss_rate_outsample * 100).toFixed(1)}%
                                                    </td>
                                                    <td className={`py-3 pr-4 text-right font-mono font-medium ${s.odds_ratio >= 1.2 ? 'text-amber-400' : s.odds_ratio >= 1.0 ? 'text-zinc-300' : 'text-rose-400'}`}>
                                                        {s.odds_ratio.toFixed(2)}x
                                                    </td>
                                                    <td className={`py-3 pr-4 text-right font-mono ${s.ic > 0 ? 'text-amber-400' : 'text-zinc-500'}`}>
                                                        {s.ic.toFixed(3)}
                                                    </td>
                                                    <td className="py-3 pr-4 text-right font-mono text-zinc-400 text-xs">
                                                        {s.p_value_corrected < 0.001 ? '<0.001' : s.p_value_corrected.toFixed(3)}
                                                    </td>
                                                    <td className="py-3 text-center">
                                                        {s.is_significant
                                                            ? <span className="px-2 py-0.5 bg-emerald-500/10 text-emerald-400 rounded-full text-xs font-bold">顯著</span>
                                                            : <span className="px-2 py-0.5 bg-rose-500/10 text-rose-400 rounded-full text-xs">不顯著</span>
                                                        }
                                                    </td>
                                                </tr>
                                                {selectedId === s.strategy_id && (
                                                    <tr>
                                                        <td colSpan={8} className="py-3">
                                                            <DetailPanel strategyId={s.strategy_id} onClose={() => setSelectedId(null)} />
                                                        </td>
                                                    </tr>
                                                )}
                                            </React.Fragment>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </>
                    )}
                </div>

                {/* Footer disclaimer */}
                <p className="text-zinc-600 text-xs text-center pb-4">
                    AlphaForge 為學習型工具，勝率為歷史統計參考，不構成投資建議。Bonferroni 校正門檻：p &lt; {result?.bonferroni_threshold.toFixed(4) ?? '…'}
                </p>
            </div>
        </>
    )
}

export default StrategyPage
