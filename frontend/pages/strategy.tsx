import React, { useEffect, useState } from 'react'
import Head from 'next/head'
import api from '../lib/api'
import {
    LineChart, Line, XAxis, YAxis, Tooltip,
    ResponsiveContainer, CartesianGrid, ReferenceLine
} from 'recharts'

// ─── History Signal (from alpha_signal_history table) ─────────────────────────
interface ApiSignalItem {
    signal_date: string; stock_id: string; stock_name: string
    time_dimension: string; trigger_count: number
    weighted_win_rate: number; weighted_odds_ratio: number
    actual_return: number | null; is_resolved: boolean
}

const THRESHOLDS: Record<string, { lo: number; hi: number }> = {
    '5d':  { lo: 3, hi: 5 },
    '10d': { lo: 3, hi: 5 },
    '30d': { lo: 5, hi: 10 },
}

// StrategyPick: 用於 PickCard 的組合資料（歷史訊號 + 現價）
interface StrategyPick {
    stock_id: string; stock_name: string
    entry_price: number; take_profit_pct: number; stop_loss_pct: number
    hold_days_max: number; strategy_count: number
    win_rate: number; trade_count: number
    time_dimension: string
}

interface SignalHistory {
    signal_date: string; actual_return: number | null; is_resolved: boolean
}

const toStars = (triggerCount: number) => {
    const n = triggerCount >= 9 ? 5 : triggerCount >= 7 ? 4 : triggerCount >= 5 ? 3 : triggerCount >= 3 ? 2 : 1
    return '★'.repeat(n)
}

const DIM_DAYS: Record<string, number> = { '5d': 5, '10d': 10, '30d': 30 }

const PickCard = ({ pick, rank }: { pick: StrategyPick; rank: number }) => {
    const [expanded, setExpanded] = useState(false)
    const [history, setHistory] = useState<SignalHistory[]>([])
    const [histLoading, setHistLoading] = useState(false)

    const takeProfit = pick.entry_price > 0 ? Math.round(pick.entry_price * (1 + pick.take_profit_pct / 100)) : 0
    const stopLoss   = pick.entry_price > 0 ? Math.round(pick.entry_price * (1 - pick.stop_loss_pct  / 100)) : 0

    const handleExpand = () => {
        const next = !expanded
        setExpanded(next)
        if (next && history.length === 0) {
            setHistLoading(true)
            api.get(`/alpha-miner/signals/history?days=180&dimension=${pick.time_dimension}`)
                .then(r => {
                    const all: (SignalHistory & { stock_id: string })[] = r.data ?? []
                    const mine = all
                        .filter(x => x.stock_id === pick.stock_id)
                        .sort((a, b) => b.signal_date.localeCompare(a.signal_date))
                        .slice(0, 8)
                    setHistory(mine)
                    setHistLoading(false)
                })
                .catch(() => setHistLoading(false))
        }
    }

    return (
        <div className="bg-zinc-900/60 border border-zinc-800 rounded-2xl px-3 py-3">
            {/* Row 1: rank + name + id + stars */}
            <div className="flex items-baseline gap-1.5 mb-1.5">
                <span className="text-zinc-600 font-mono text-xs shrink-0 w-5">#{rank}</span>
                <span className="text-white font-bold text-xl leading-none">{pick.stock_name}</span>
                <span className="text-zinc-500 text-sm">{pick.stock_id}</span>
                <span className="ml-auto text-amber-400 text-base shrink-0 tracking-tight">{toStars(pick.strategy_count)}</span>
            </div>

            {/* Row 2: entry price → take profit / stop loss */}
            {pick.entry_price > 0 && (
                <div className="flex items-baseline gap-2 mb-1.5">
                    <span className="text-zinc-500 text-xs">買入</span>
                    <span className="text-zinc-300 font-mono font-bold text-lg">{pick.entry_price.toLocaleString()}</span>
                    <span className="text-zinc-600">→</span>
                    <span className="text-zinc-500 text-xs">停利</span>
                    <span className="text-rose-400 font-mono font-bold text-lg">▲{takeProfit.toLocaleString()}</span>
                    <span className="text-zinc-700">/</span>
                    <span className="text-zinc-500 text-xs">停損</span>
                    <span className="text-emerald-400 font-mono font-bold text-lg">▼{stopLoss.toLocaleString()}</span>
                </div>
            )}

            {/* Row 3: meta + expand toggle */}
            <div
                className="flex items-center gap-2 text-sm text-zinc-500 whitespace-nowrap overflow-hidden cursor-pointer select-none"
                onClick={handleExpand}
            >
                <span>{pick.strategy_count} 策略</span>
                <span className="text-zinc-700">·</span>
                <span>持有{pick.hold_days_max}天</span>
                <span className="text-zinc-700">·</span>
                <span>漲&gt;{pick.take_profit_pct}%機率</span>
                <span className={`font-mono ${pick.win_rate >= 30 ? 'text-rose-400' : 'text-zinc-400'}`}>{pick.win_rate.toFixed(1)}%</span>
                <span className="ml-auto text-zinc-600 text-xs">{expanded ? '▲' : '▼'}</span>
            </div>

            {/* Expanded: 真實歷史訊號 */}
            {expanded && (
                <div className="mt-3 border-t border-zinc-800 pt-3">
                    {/* 說明：勝率的定義 */}
                    <p className="text-zinc-600 text-xs mb-2.5 leading-relaxed">
                        「漲&gt;{pick.take_profit_pct}%機率」= 此訊號歷史上持有{pick.hold_days_max}天後漲幅超過{pick.take_profit_pct}%的比率（樣本外測試集）
                    </p>

                    {histLoading && <p className="text-zinc-600 text-xs">載入中…</p>}

                    {!histLoading && history.length === 0 && (
                        <p className="text-zinc-600 text-xs">此股票近 180 天無歷史訊號紀錄</p>
                    )}
                    {!histLoading && history.length > 0 && (
                        <p className="text-zinc-700 text-xs mb-2">
                            ※ 早期歷史訊號為模型回算結果，非當日即時訊號
                        </p>
                    )}

                    {!histLoading && history.length > 0 && (
                        <>
                            <div className="grid grid-cols-3 text-xs text-zinc-600 uppercase tracking-widest mb-1.5 px-1">
                                <span>訊號日期</span>
                                <span className="text-right">狀態</span>
                                <span className="text-right">實際報酬</span>
                            </div>
                            {history.map((h, i) => {
                                const ret = h.actual_return
                                const retPct = ret !== null ? (ret * 100).toFixed(1) : null
                                const isWin = ret !== null && ret * 100 >= pick.take_profit_pct
                                return (
                                    <div key={i} className="grid grid-cols-3 text-xs py-1.5 px-1 border-t border-zinc-800/50">
                                        <span className="text-zinc-500 font-mono">{h.signal_date.slice(5)}</span>
                                        <span className={`text-right font-medium ${!h.is_resolved ? 'text-zinc-600' : isWin ? 'text-rose-400' : 'text-zinc-400'}`}>
                                            {!h.is_resolved ? '持有中' : isWin ? '達標' : '未達標'}
                                        </span>
                                        <span className={`text-right font-mono font-bold ${ret === null ? 'text-zinc-700' : ret >= 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                                            {retPct !== null ? `${ret! >= 0 ? '+' : ''}${retPct}%` : '—'}
                                        </span>
                                    </div>
                                )
                            })}
                        </>
                    )}
                </div>
            )}
        </div>
    )
}

// ─── 因子白話描述 ──────────────────────────────────────────────────────────────
const FACTOR_DESC: Record<string, string> = {
    rsi14:           'RSI 超賣反彈',
    k:               'KD-K 動能',
    d:               'KD-D 趨勢',
    macd_dif:        'MACD 多空強度',
    macd_osc:        'MACD 柱狀動能',
    bias5:           '5日乖離回歸',
    bias10:          '10日乖離回歸',
    bias20:          '20日乖離回歸',
    bb_pctb:         '布林通道位置',
    vol_ratio:       '成交量異常放大',
    yield_rate:      '高現金殖利率',
    roe:             '股東權益報酬率',
    pb_ratio:        '股淨比估值',
    revenue_yoy:     '年營收成長',
    foreign_net_buy: '外資單日買超',
    foreign_buy_5d:  '外資5日累積買超',
    trust_net_buy:   '投信單日買超',
    trust_buy_5d:    '投信5日累積買超',
    margin_chg_5d:   '融資5日變化',
    dealer_net_buy:  '自營商單日買超',
    dealer_buy_5d:   '自營商5日累積買超',
    price_vs_high20: '距近期高點距離',
    ma_trend:        '均線多頭排列',
}

const buildStrategyDesc = (factors: string[], weights?: { factor: string; coefficient: number }[]): string => {
    const weightMap = Object.fromEntries((weights ?? []).map(w => [w.factor, w.coefficient]))
    const parts = factors.map(f => {
        const desc = FACTOR_DESC[f] ?? f
        const coef = weightMap[f]
        if (coef === undefined) return `「${desc}」`
        const sign = coef > 0 ? '+' : ''
        return `「${desc} (${sign}${coef.toFixed(2)})」`
    })
    if (parts.length === 1) return `以 ${parts[0]} 為訊號的單因子策略`
    return `${parts.slice(0, -1).join('、')} 與 ${parts[parts.length - 1]} 的多因子策略`
}

// ─── Types ────────────────────────────────────────────────────────────────────
interface FactorWeight { factor: string; factor_label: string; coefficient: number; direction: string }
interface EquityCurvePoint { date: string; cumulative_return: number }
interface RecentAlphaSignal {
    stock_id: string; stock_name: string; signal_date: string
    predicted_prob: number; trigger_factors: string[]
}
interface StrategyRanking {
    strategy_id: string; strategy_name: string; factors: string[]
    time_dimension: string; threshold_low: number; threshold_high: number
    win_rate_insample: number; win_rate_outsample: number; win_rate_outsample_hi: number
    loss_rate_outsample: number; loss_rate_outsample_hi: number
    odds_ratio: number; odds_ratio_hi: number
    market_win_rate: number; market_win_rate_hi: number
    market_loss_rate: number; market_loss_rate_hi: number
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
interface AlphaMinerResult {
    strategies: StrategyRanking[]; last_trained: string
    train_period: string; test_period: string
    total_combinations_tested: number; bonferroni_threshold: number
    is_training: boolean
}

type DimKey = '5d' | '10d' | '30d'
const DIM_CONFIG: Record<DimKey, { label: string; shortLabel: string; desc: string }> = {
    '5d':  { label: '5日持有',  shortLabel: '5日', desc: '門檻 3% / 5%' },
    '10d': { label: '10日持有', shortLabel: '10日', desc: '門檻 3% / 5%' },
    '30d': { label: '30日持有', shortLabel: '30日', desc: '門檻 5% / 10%' },
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
const pct = (v: number, d = 1) => `${v >= 0 ? '+' : ''}${(v * 100).toFixed(d)}%`
const toPct = (v: number, d = 1) => `${(v * 100).toFixed(d)}%`

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

// ─── Stat Pill ─────────────────────────────────────────────────────────────
const StatPill = ({ label, value, color }: { label: string; value: string; color: string }) => (
    <div className="flex flex-col items-center bg-zinc-800/50 rounded-xl px-3 py-2.5 min-w-0">
        <span className="text-zinc-500 text-xs leading-tight mb-1 whitespace-nowrap">{label}</span>
        <span className={`text-sm font-bold font-mono ${color}`}>{value}</span>
    </div>
)

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
    const tlo = detail ? Math.round(detail.threshold_low * 100) : 3
    const thi = detail ? Math.round(detail.threshold_high * 100) : 5

    return (
        <div className="bg-zinc-900 border border-zinc-700/60 rounded-2xl overflow-hidden">
            {/* Panel Header */}
            <div className="flex items-start justify-between px-4 py-3 border-b border-zinc-800">
                <div className="min-w-0 pr-4">
                    <p className="text-white font-semibold text-sm truncate">{detail?.strategy_name ?? '…'}</p>
                    {detail && (
                        <p className="text-zinc-500 text-xs mt-0.5 leading-relaxed">
                            {buildStrategyDesc(detail.factors, detail.factor_weights)}
                        </p>
                    )}
                </div>
                <button
                    onClick={onClose}
                    className="shrink-0 text-zinc-500 hover:text-zinc-200 text-xs px-3 py-1.5 rounded-lg border border-zinc-700 hover:border-zinc-500 transition-colors cursor-pointer"
                >
                    收起
                </button>
            </div>

            <div className="px-3 pb-4 space-y-4">
                {loading ? (
                    <div className="space-y-3">{Array(3).fill(0).map((_, i) => <Skeleton key={i} className="h-16" />)}</div>
                ) : !detail ? (
                    <p className="text-zinc-500 text-sm text-center py-4">載入失敗</p>
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

                        {/* 左右兩欄：按門檻分組 */}
                        <div className="grid grid-cols-2 gap-2">
                            {[
                                {
                                    label: `漲跌${tlo}%`,
                                    oddsVal: detail.odds_ratio,
                                    winStrat: detail.win_rate_outsample, winMkt: detail.market_win_rate,
                                    lossStrat: detail.loss_rate_outsample, lossMkt: detail.market_loss_rate,
                                    thr: tlo,
                                },
                                {
                                    label: `漲跌${thi}%`,
                                    oddsVal: detail.odds_ratio_hi,
                                    winStrat: detail.win_rate_outsample_hi, winMkt: detail.market_win_rate_hi,
                                    lossStrat: detail.loss_rate_outsample_hi, lossMkt: detail.market_loss_rate_hi,
                                    thr: thi,
                                },
                            ].map((col, i) => (
                                <div key={i} className="bg-zinc-800/50 rounded-xl px-2.5 py-1.5 space-y-0.5">
                                    <p className="text-zinc-400 text-xs text-center mb-1">{col.label}</p>
                                    {/* 賠率比 */}
                                    <div className="flex justify-between items-baseline">
                                        <span className="text-zinc-400 text-xs">賠率比</span>
                                        <span className={`text-base font-bold font-mono ${col.oddsVal >= 1.2 ? 'text-amber-400' : col.oddsVal >= 1.0 ? 'text-zinc-200' : 'text-rose-400'}`}>
                                            {col.oddsVal.toFixed(2)}x
                                        </span>
                                    </div>
                                    {/* 勝率：策略 */}
                                    <div className="flex justify-between items-baseline">
                                        <span className="text-zinc-400 text-xs">策略 勝率</span>
                                        <span className={`text-base font-bold font-mono ${col.winStrat > col.winMkt ? 'text-emerald-400' : 'text-rose-400'}`}>{toPct(col.winStrat)}</span>
                                    </div>
                                    {/* 勝率：市場 */}
                                    <div className="flex justify-between items-baseline">
                                        <span className="text-zinc-500 text-xs">市場 勝率</span>
                                        <span className="text-base font-bold font-mono text-zinc-500">{toPct(col.winMkt)}</span>
                                    </div>
                                    {/* 踩雷：策略 */}
                                    <div className="flex justify-between items-baseline">
                                        <span className="text-zinc-400 text-xs">策略 踩雷</span>
                                        {col.lossStrat > 0 || i === 0
                                            ? <span className={`text-base font-bold font-mono ${col.lossStrat < col.lossMkt ? 'text-emerald-400' : 'text-rose-400'}`}>{toPct(col.lossStrat)}</span>
                                            : <span className="text-zinc-700 text-base font-bold font-mono">—</span>
                                        }
                                    </div>
                                    {/* 踩雷：市場 */}
                                    <div className="flex justify-between items-baseline">
                                        <span className="text-zinc-500 text-xs">市場 踩雷</span>
                                        {col.lossMkt > 0 || i === 0
                                            ? <span className="text-base font-bold font-mono text-zinc-500">{toPct(col.lossMkt)}</span>
                                            : <span className="text-zinc-700 text-base font-bold font-mono">—</span>
                                        }
                                    </div>
                                </div>
                            ))}
                        </div>

                        {/* IC */}
                        <div className="grid grid-cols-2 gap-2">
                            <StatPill label="IC" value={detail.ic.toFixed(3)} color={detail.ic > 0 ? 'text-amber-400' : 'text-zinc-400'} />
                            <StatPill label="測試訊號數" value={detail.sample_count_test.toLocaleString()} color="text-zinc-300" />
                        </div>

                        {/* Factor weights */}
                        <div>
                            <p className="text-zinc-500 text-xs uppercase tracking-widest mb-3">因子權重係數</p>
                            <div className="space-y-2.5">
                                {detail.factor_weights.map((fw, i) => (
                                    <div key={i} className="flex items-center gap-3">
                                        <span className="text-zinc-400 text-xs w-20 text-right shrink-0 leading-tight">{fw.factor_label}</span>
                                        <div className="flex-1 bg-zinc-800 rounded-full h-1.5">
                                            <div
                                                className={`h-1.5 rounded-full transition-all ${fw.direction === 'bullish' ? 'bg-emerald-500' : 'bg-rose-500'}`}
                                                style={{ width: `${Math.abs(fw.coefficient) / maxCoef * 100}%` }}
                                            />
                                        </div>
                                        <span className={`text-xs font-mono w-12 shrink-0 text-right ${fw.direction === 'bullish' ? 'text-emerald-400' : 'text-rose-400'}`}>
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
                                <ResponsiveContainer width="100%" height={160}>
                                    <LineChart data={detail.equity_curve.map(p => ({ date: p.date, value: p.cumulative_return }))} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
                                        <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                                        <XAxis dataKey="date" tick={{ fill: '#52525b', fontSize: 8 }} tickLine={false} interval="preserveStartEnd" />
                                        <YAxis tickFormatter={v => pct(v, 0)} tick={{ fill: '#52525b', fontSize: 8 }} tickLine={false} axisLine={false} width={40} />
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
                                <p className="text-zinc-500 text-xs uppercase tracking-widest mb-2.5">近期訊號（最新交易日）</p>
                                <div className="flex flex-wrap gap-2">
                                    {detail.recent_signals.map((sig, i) => (
                                        <div key={i} className="bg-zinc-800/60 border border-zinc-700 rounded-xl px-3 py-2 text-xs flex items-center gap-1.5">
                                            <span className="text-white font-medium">{sig.stock_name}</span>
                                            <span className="text-zinc-500">{sig.stock_id}</span>
                                            <span className="text-amber-400 font-mono font-bold">{(sig.predicted_prob * 100).toFixed(0)}%</span>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}
                    </>
                )}
            </div>
        </div>
    )
}

// ─── Mobile Strategy Card ─────────────────────────────────────────────────────
const MobileCard = ({
    s, idx, tlo, thi, dimLabel, isSelected, onToggle
}: {
    s: StrategyRanking; idx: number; tlo: number; thi: number; dimLabel: string; isSelected: boolean; onToggle: () => void
}) => {
    const winLo = s.win_rate_outsample
    const winHi = s.win_rate_outsample_hi
    const loss = s.loss_rate_outsample

    return (
        <div className={`rounded-2xl border transition-colors duration-200 overflow-hidden ${isSelected ? 'border-zinc-600 bg-zinc-800/40' : 'border-zinc-800 bg-zinc-900/40'}`}>
            <button
                onClick={onToggle}
                className="w-full text-left px-4 py-4 cursor-pointer active:bg-zinc-800/50"
            >
                {/* Row 1: Rank + Name + Badge */}
                <div className="flex items-start gap-2.5 mb-3.5">
                    <span className="text-zinc-600 font-mono text-sm mt-0.5 w-6 shrink-0 text-right">#{idx + 1}</span>
                    <div className="flex-1 min-w-0">
                        <p className="text-zinc-100 text-base font-semibold leading-snug">
                            {s.strategy_name}
                            {s.overfit_warning && <span className="ml-1.5 text-amber-500 text-sm">⚠</span>}
                        </p>
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                        <span className="px-1.5 py-0.5 rounded-md text-[10px] font-semibold bg-zinc-700/60 text-zinc-400 border border-zinc-700">
                            {dimLabel}
                        </span>
                        {s.is_significant
                            ? <span className="px-2.5 py-1 bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 rounded-full text-xs font-bold">顯著</span>
                            : <span className="px-2.5 py-1 bg-zinc-800 text-zinc-500 border border-zinc-700 rounded-full text-xs">不顯著</span>
                        }
                    </div>
                </div>

                {/* Row 2: 低門檻 | 高門檻 兩欄 */}
                <div className="grid grid-cols-2 gap-2 pl-8">
                    {/* 低門檻區塊 */}
                    <div className="bg-zinc-800/50 rounded-xl px-2.5 py-1.5 space-y-0.5">
                        <p className="text-zinc-400 text-xs text-center mb-1">漲跌{tlo}%</p>
                        <div className="flex justify-between items-baseline">
                            <span className="text-zinc-400 text-xs">賠率比</span>
                            <span className={`text-base font-bold font-mono ${s.odds_ratio >= 1.2 ? 'text-amber-400' : s.odds_ratio >= 1.0 ? 'text-zinc-200' : 'text-rose-400'}`}>
                                {s.odds_ratio.toFixed(2)}x
                            </span>
                        </div>
                        <div className="flex justify-between items-baseline">
                            <span className="text-zinc-400 text-xs">&gt;{tlo}% 勝率</span>
                            <span className={`text-base font-bold font-mono ${winLo > s.market_win_rate ? 'text-emerald-400' : 'text-rose-400'}`}>
                                {toPct(winLo)}
                            </span>
                        </div>
                        <div className="flex justify-between items-baseline">
                            <span className="text-zinc-400 text-xs">&lt;-{tlo}% 踩雷</span>
                            <span className={`text-base font-bold font-mono ${loss < s.market_loss_rate ? 'text-emerald-400' : 'text-rose-400'}`}>
                                {toPct(loss)}
                            </span>
                        </div>
                    </div>
                    {/* 高門檻區塊 */}
                    <div className="bg-zinc-800/50 rounded-xl px-2.5 py-1.5 space-y-0.5">
                        <p className="text-zinc-400 text-xs text-center mb-1">漲跌{thi}%</p>
                        <div className="flex justify-between items-baseline">
                            <span className="text-zinc-400 text-xs">賠率比</span>
                            <span className={`text-base font-bold font-mono ${s.odds_ratio_hi >= 1.2 ? 'text-amber-400' : s.odds_ratio_hi >= 1.0 ? 'text-zinc-200' : 'text-rose-400'}`}>
                                {s.odds_ratio_hi.toFixed(2)}x
                            </span>
                        </div>
                        <div className="flex justify-between items-baseline">
                            <span className="text-zinc-400 text-xs">&gt;{thi}% 勝率</span>
                            <span className={`text-base font-bold font-mono ${winHi > s.market_win_rate_hi ? 'text-emerald-400' : 'text-rose-400'}`}>
                                {toPct(winHi)}
                            </span>
                        </div>
                        <div className="flex justify-between items-baseline">
                            <span className="text-zinc-400 text-xs">&lt;-{thi}% 踩雷</span>
                            <span className={`text-base font-bold font-mono ${s.loss_rate_outsample_hi < s.market_loss_rate_hi ? 'text-emerald-400' : 'text-rose-400'}`}>
                                {toPct(s.loss_rate_outsample_hi)}
                            </span>
                        </div>
                    </div>
                </div>
            </button>

            {/* Detail Panel */}
            {isSelected && (
                <div className="px-3 pb-3">
                    <DetailPanel strategyId={s.strategy_id} onClose={onToggle} />
                </div>
            )}
        </div>
    )
}

// ─── Main Page ────────────────────────────────────────────────────────────────
const StrategyPage = () => {
    const [picks, setPicks] = useState<StrategyPick[]>([])
    const [signalDate, setSignalDate] = useState<string>('')
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)

    useEffect(() => {
        const loadSignals = async () => {
            try {
                // 並行呼叫 3 個維度的 history API（取最近 2 天確保拿到最新訊號日）
                const [r5, r10, r30] = await Promise.all([
                    api.get('/alpha-miner/signals/history?days=2&dimension=5d'),
                    api.get('/alpha-miner/signals/history?days=2&dimension=10d'),
                    api.get('/alpha-miner/signals/history?days=2&dimension=30d'),
                ])

                const all: ApiSignalItem[] = [
                    ...(r5.data ?? []),
                    ...(r10.data ?? []),
                    ...(r30.data ?? []),
                ]

                if (all.length === 0) {
                    setLoading(false)
                    return
                }

                // 取最新 signal_date
                const maxDate = all.reduce((m, s) => s.signal_date > m ? s.signal_date : m, '')
                const latest = all.filter(s => s.signal_date === maxDate)
                setSignalDate(maxDate)

                // 按 stock_id 去重：保留 trigger_count 最高者（不同維度同一股票）
                const map = new Map<string, ApiSignalItem>()
                for (const s of latest) {
                    const existing = map.get(s.stock_id)
                    if (!existing || s.trigger_count > existing.trigger_count) map.set(s.stock_id, s)
                }
                const signals = Array.from(map.values()).sort((a, b) => b.trigger_count - a.trigger_count)

                // 批次查現價
                const priceResults = await Promise.allSettled(
                    signals.map(s => api.get(`/stocks/${s.stock_id}/quote`))
                )

                const combined: StrategyPick[] = signals.map((s, i) => {
                    const priceRes = priceResults[i]
                    const price: number = priceRes.status === 'fulfilled'
                        ? (priceRes.value.data?.current_price ?? 0)
                        : 0
                    const { lo, hi } = THRESHOLDS[s.time_dimension] ?? { lo: 3, hi: 5 }
                    const days = DIM_DAYS[s.time_dimension] ?? 10
                    return {
                        stock_id:        s.stock_id,
                        stock_name:      s.stock_name,
                        entry_price:     price,
                        take_profit_pct: hi,
                        stop_loss_pct:   lo,
                        hold_days_max:   days,
                        strategy_count:  s.trigger_count,
                        win_rate:        s.weighted_win_rate * 100,
                        trade_count:     Math.round(s.trigger_count * 3.5),
                        time_dimension:  s.time_dimension,
                    }
                })

                setPicks(combined)
                setLoading(false)
            } catch (e: any) {
                setError(e.message)
                setLoading(false)
            }
        }
        loadSignals()
    }, [])

    const displayDate = signalDate
        ? new Date(signalDate).toLocaleDateString('zh-TW', { month: '2-digit', day: '2-digit' })
        : new Date().toLocaleDateString('zh-TW', { month: '2-digit', day: '2-digit' })

    return (
        <>
            <Head><title>每日精選 | AlphaForge</title></Head>
            <div className="min-h-[calc(100vh-64px)] flex flex-col gap-4 sm:gap-6 max-w-7xl mx-auto px-3 sm:px-6 lg:px-8 py-4 sm:py-8">

                {/* ── Header ───────────────────────────────────────────── */}
                <div className="relative overflow-hidden bg-zinc-900/40 border border-zinc-800/60 rounded-2xl sm:rounded-3xl p-4 sm:p-8">
                    <div className="absolute top-0 right-0 w-48 h-48 sm:w-64 sm:h-64 bg-amber-500/5 rounded-full blur-3xl -mr-24 -mt-24 pointer-events-none" />
                    <div className="relative flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                        <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-3">
                                <span className="absolute top-0 right-0 px-2.5 py-1 bg-zinc-800 border border-zinc-700 text-zinc-500 rounded-full text-xs font-mono">開發中</span>
                                <h1 className="text-2xl sm:text-4xl font-bold tracking-tight text-white leading-tight flex items-center gap-2">
                                    <svg viewBox="0 0 24 24" width="28" height="28" className="fill-amber-400 shrink-0 self-center">
                                        <path d="M16,6L18.29,8.29L13.42,13.17L9.42,9.17L2,16.59L3.41,18L9.42,12L13.42,16L19.71,9.71L22,12V6H16Z" />
                                    </svg>
                                    每日{' '}
                                    <span className="bg-gradient-to-r from-amber-400 to-yellow-500 bg-clip-text text-transparent">精選</span>
                                </h1>
                                <span className="text-zinc-500 text-sm font-mono self-center">{displayDate}</span>
                            </div>
                            <p className="text-zinc-500 text-sm sm:text-base mt-1.5 leading-relaxed">
                                量化模型每日精算 · 多策略共振選股 · 勝率為歷史統計參考，不構成投資建議。
                            </p>
                        </div>
                    </div>
                </div>

                {error && (
                    <div className="bg-rose-900/20 border border-rose-800/50 rounded-2xl p-4 text-rose-400 text-sm">
                        載入失敗：{error}
                    </div>
                )}

                {/* ── 今日精選 ──────────────────────────────────────────── */}
                <div className="flex flex-col gap-2">
                    {loading && (
                        [1, 2, 3].map(i => (
                            <div key={i} className="bg-zinc-900/60 border border-zinc-800 rounded-2xl px-3 py-3 animate-pulse">
                                <div className="h-6 bg-zinc-800 rounded w-1/3 mb-2" />
                                <div className="h-4 bg-zinc-800 rounded w-2/3 mb-2" />
                                <div className="h-4 bg-zinc-800 rounded w-1/2" />
                            </div>
                        ))
                    )}
                    {!loading && picks.length === 0 && !error && (
                        <div className="bg-zinc-900/40 border border-zinc-800/60 rounded-2xl p-8 text-center">
                            <p className="text-zinc-500 text-sm">今日暫無訊號</p>
                            <p className="text-zinc-600 text-xs mt-1">模型尚未完成今日掃描，或今日無符合條件標的</p>
                        </div>
                    )}
                    {picks.map((pick, i) => (
                        <PickCard key={pick.stock_id} pick={pick} rank={i + 1} />
                    ))}
                </div>

            </div>
        </>
    )
}

export default StrategyPage
