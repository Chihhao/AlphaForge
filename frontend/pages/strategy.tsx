import React, { useEffect, useState } from 'react'
import Head from 'next/head'
import api from '../lib/api'
import {
    LineChart, Line, XAxis, YAxis, Tooltip,
    ResponsiveContainer, CartesianGrid, ReferenceLine
} from 'recharts'

// ─── Strategy Miner Mock Data ─────────────────────────────────────────────────
interface StrategyPick {
    stock_id: string; stock_name: string
    entry_price: number; take_profit_pct: number; stop_loss_pct: number
    hold_days_max: number; weighted_score: number; strategy_count: number
    win_rate: number; avg_return: number; trade_count: number
}

const MOCK_PICKS: StrategyPick[] = [
    { stock_id: '2330', stock_name: '台積電',   entry_price: 895,  take_profit_pct: 8,  stop_loss_pct: 5, hold_days_max: 10, weighted_score: 4.21, strategy_count: 6, win_rate: 64, avg_return: 3.2, trade_count: 22 },
    { stock_id: '2454', stock_name: '聯發科',   entry_price: 1230, take_profit_pct: 8,  stop_loss_pct: 5, hold_days_max: 10, weighted_score: 3.87, strategy_count: 5, win_rate: 61, avg_return: 2.8, trade_count: 19 },
    { stock_id: '6505', stock_name: '台塑化',   entry_price: 88,   take_profit_pct: 5,  stop_loss_pct: 3, hold_days_max: 10, weighted_score: 3.54, strategy_count: 5, win_rate: 58, avg_return: 2.1, trade_count: 31 },
    { stock_id: '2317', stock_name: '鴻海',     entry_price: 182,  take_profit_pct: 8,  stop_loss_pct: 5, hold_days_max: 20, weighted_score: 3.31, strategy_count: 4, win_rate: 60, avg_return: 3.5, trade_count: 17 },
    { stock_id: '2308', stock_name: '台達電',   entry_price: 365,  take_profit_pct: 8,  stop_loss_pct: 5, hold_days_max: 10, weighted_score: 3.10, strategy_count: 4, win_rate: 57, avg_return: 2.6, trade_count: 21 },
    { stock_id: '3008', stock_name: '大立光',   entry_price: 2100, take_profit_pct: 12, stop_loss_pct: 8, hold_days_max: 20, weighted_score: 2.98, strategy_count: 4, win_rate: 55, avg_return: 4.1, trade_count: 13 },
    { stock_id: '2382', stock_name: '廣達',     entry_price: 245,  take_profit_pct: 8,  stop_loss_pct: 5, hold_days_max: 10, weighted_score: 2.74, strategy_count: 4, win_rate: 62, avg_return: 2.9, trade_count: 18 },
    { stock_id: '2379', stock_name: '瑞昱',     entry_price: 590,  take_profit_pct: 8,  stop_loss_pct: 5, hold_days_max: 10, weighted_score: 2.61, strategy_count: 4, win_rate: 59, avg_return: 2.3, trade_count: 24 },
    { stock_id: '4938', stock_name: '和碩',     entry_price: 77,   take_profit_pct: 5,  stop_loss_pct: 3, hold_days_max: 10, weighted_score: 2.43, strategy_count: 4, win_rate: 56, avg_return: 1.8, trade_count: 28 },
    { stock_id: '2303', stock_name: '聯電',     entry_price: 48,   take_profit_pct: 5,  stop_loss_pct: 3, hold_days_max: 10, weighted_score: 2.20, strategy_count: 4, win_rate: 54, avg_return: 1.5, trade_count: 33 },
]

// ─── Today Pick Card ──────────────────────────────────────────────────────────
const toStars = (score: number) => {
    const n = score >= 4.0 ? 5 : score >= 3.5 ? 4 : score >= 3.0 ? 3 : score >= 2.5 ? 2 : 1
    return '★'.repeat(n)
}

const PickCard = ({ pick, rank }: { pick: StrategyPick; rank: number }) => {
    const takeProfit = Math.round(pick.entry_price * (1 + pick.take_profit_pct / 100))
    const stopLoss   = Math.round(pick.entry_price * (1 - pick.stop_loss_pct  / 100))

    return (
        <div className="border-b border-zinc-800 px-3 py-3 last:border-0">
            {/* Row 1: rank + name + id + score */}
            <div className="flex items-baseline gap-1.5 mb-1.5">
                <span className="text-zinc-600 font-mono text-xs shrink-0 w-5">#{rank}</span>
                <span className="text-white font-bold text-xl leading-none">{pick.stock_name}</span>
                <span className="text-zinc-500 text-sm">{pick.stock_id}</span>
                <span className="ml-auto text-amber-400 text-base shrink-0 tracking-tight">{toStars(pick.weighted_score)}</span>
            </div>

            {/* Row 2: prices */}
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

            {/* Row 3: meta — all on one line, no wrapping */}
            <div className="flex items-center gap-2 text-sm text-zinc-500 whitespace-nowrap overflow-hidden">
                <span>{pick.strategy_count} 策略</span>
                <span className="text-zinc-700">·</span>
                <span>{pick.hold_days_max}天</span>
                <span className="text-zinc-700">·</span>
                <span className={pick.win_rate >= 60 ? 'text-rose-400' : ''}>勝率{pick.win_rate}%</span>
                <span className="text-zinc-700">·</span>
                <span className="text-rose-400">均+{pick.avg_return}%</span>
                <span className="text-zinc-700">·</span>
                <span>{pick.trade_count}筆</span>
            </div>
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
    const [result, setResult] = useState<AlphaMinerResult | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [selectedId, setSelectedId] = useState<string | null>(null)
    const [dim, setDim] = useState<DimKey>('10d')

    useEffect(() => {
        let timer: ReturnType<typeof setTimeout>
        const fetch = () => {
            api.get('/alpha-miner/strategies')
                .then(r => {
                    setResult(r.data)
                    setLoading(false)
                    if (r.data.is_training) {
                        timer = setTimeout(fetch, 15000)
                    }
                })
                .catch(e => { setError(e.message); setLoading(false) })
        }
        fetch()
        return () => clearTimeout(timer)
    }, [])

    const strategies = (result?.strategies ?? []).filter(s => s.time_dimension === dim)
    const tlo = dim === '30d' ? 5 : 3
    const thi = dim === '30d' ? 10 : 5

    return (
        <>
            <Head><title>策略推薦 | AlphaForge</title></Head>
            <div className="min-h-[calc(100vh-64px)] flex flex-col gap-4 sm:gap-6 max-w-7xl mx-auto px-3 sm:px-6 lg:px-8 py-4 sm:py-8">

                {/* ── Header ───────────────────────────────────────────── */}
                <div className="relative overflow-hidden bg-zinc-900/40 border border-zinc-800/60 rounded-2xl sm:rounded-3xl p-4 sm:p-8">
                    <div className="absolute top-0 right-0 w-48 h-48 sm:w-64 sm:h-64 bg-amber-500/5 rounded-full blur-3xl -mr-24 -mt-24 pointer-events-none" />
                    <div className="relative flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                        <div className="flex-1 min-w-0">
                            <h1 className="text-2xl sm:text-4xl font-bold tracking-tight text-white leading-tight">
                                Alpha Miner{' '}
                                <span className="bg-gradient-to-r from-amber-400 to-yellow-500 bg-clip-text text-transparent">策略金鑰</span>
                            </h1>
                            <p className="text-zinc-500 text-sm sm:text-base mt-1.5 leading-relaxed">
                                {result
                                    ? `${result.strategies.filter(s => s.is_significant).length} 組顯著策略（共 ${result.strategies.length} 組）· ${result.total_combinations_tested} 組因子 × 3 持有期 · 訓練 ${result.train_period} · 測試 ${result.test_period}`
                                    : loading ? '載入中…' : 'Alpha Miner 多因子邏輯迴歸'
                                }
                            </p>
                        </div>
                    </div>
                </div>

                {error && (
                    <div className="bg-rose-900/20 border border-rose-800/50 rounded-2xl p-4 text-rose-400 text-sm">
                        載入失敗：{error}
                    </div>
                )}

                {/* ── 今日推薦 ──────────────────────────────────────────── */}
                <div className="bg-zinc-900/40 border border-zinc-800/60 rounded-2xl sm:rounded-3xl p-3 sm:p-5">
                    <div className="flex items-center justify-between mb-4">
                        <div>
                            <p className="text-sm font-bold text-zinc-500 uppercase tracking-widest border-l-2 border-amber-500 pl-2">
                                今日推薦
                            </p>
                            <p className="text-zinc-600 text-xs mt-0.5 pl-3">盤後計算 · 明日開盤參考買入 · 最多 10 檔</p>
                        </div>
                        <span className="px-2.5 py-1 bg-zinc-800 border border-zinc-700 text-zinc-500 rounded-full text-xs">
                            模擬資料（Strategy Miner 開發中）
                        </span>
                    </div>

                    <div className="bg-zinc-900/60 border border-zinc-800 rounded-2xl overflow-hidden">
                        {MOCK_PICKS.map((pick, i) => (
                            <PickCard key={pick.stock_id} pick={pick} rank={i + 1} />
                        ))}
                    </div>
                </div>

                {/* ── Alpha Miner 策略庫（縮小呈現） ─────────────────────── */}
                <div>
                    <p className="text-xs font-bold text-zinc-600 uppercase tracking-widest border-l-2 border-zinc-700 pl-2 mb-3">
                        Alpha Miner 策略庫
                    </p>
                </div>

                {/* ── Dimension Tabs ────────────────────────────────────── */}
                <div className="flex gap-2">
                    {(Object.keys(DIM_CONFIG) as DimKey[]).map(key => {
                        const cfg = DIM_CONFIG[key]
                        const active = dim === key
                        return (
                            <button
                                key={key}
                                onClick={() => { setDim(key); setSelectedId(null) }}
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

                {/* ── Strategy List ─────────────────────────────────────── */}
                <div className="flex-1">
                    {/* Market baseline banner */}
                    {strategies.length > 0 && (
                        <div className="flex items-center gap-2 mb-3 px-1">
                            <span className="text-zinc-600 text-xs uppercase tracking-widest">市場基準</span>
                            <span className="text-zinc-500 text-xs">
                                &gt;{tlo}% 勝率 {toPct(strategies[0]?.market_win_rate ?? 0)}
                                ・&gt;{thi}% 勝率 {toPct(strategies[0]?.market_win_rate_hi ?? 0)}
                            </span>
                        </div>
                    )}

                    {loading ? (
                        <div className="space-y-2.5">
                            {Array(6).fill(0).map((_, i) => <Skeleton key={i} className="h-28" />)}
                        </div>
                    ) : strategies.length === 0 ? (
                        <div className="h-40 flex flex-col items-center justify-center gap-2 text-zinc-600 text-sm bg-zinc-900/30 border border-zinc-800 rounded-2xl">
                            <span className="text-2xl">⛏</span>
                            {result?.is_training ? '模型訓練中，每 15 秒自動更新…' : '尚無資料（stock_features 資料不足）'}
                        </div>
                    ) : (
                        <>
                            {/* ── 手機版：卡片列表 ─────────────────────── */}
                            <div className="md:hidden space-y-2.5">
                                {strategies.map((s, idx) => (
                                    <MobileCard
                                        key={s.strategy_id}
                                        s={s}
                                        idx={idx}
                                        tlo={tlo}
                                        thi={thi}
                                        dimLabel={`${DIM_CONFIG[dim].shortLabel}後`}
                                        isSelected={selectedId === s.strategy_id}
                                        onToggle={() => setSelectedId(selectedId === s.strategy_id ? null : s.strategy_id)}
                                    />
                                ))}
                            </div>

                            {/* ── 桌機版：表格 ─────────────────────────── */}
                            <div className="hidden md:block bg-zinc-900/50 border border-zinc-800 rounded-2xl p-5">
                                <div className="overflow-x-auto">
                                    <table className="w-full text-sm">
                                        <thead>
                                            <tr className="text-zinc-600 text-xs uppercase tracking-widest border-b border-zinc-800">
                                                <th className="text-left py-2 pr-4 w-8">#</th>
                                                <th className="text-left py-2 pr-6">策略名稱</th>
                                                <th className="text-right py-2 pr-4">勝率 &gt;{tlo}%</th>
                                                <th className="text-right py-2 pr-4">勝率 &gt;{thi}%</th>
                                                <th className="text-right py-2 pr-4">踩雷 &lt;-{tlo}%</th>
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
                                                        className={`border-b border-zinc-800/50 cursor-pointer transition-colors duration-150 ${selectedId === s.strategy_id ? 'bg-zinc-800/40' : 'hover:bg-zinc-800/20'}`}
                                                    >
                                                        <td className="py-3 pr-4 text-zinc-600 font-mono text-xs">{idx + 1}</td>
                                                        <td className="py-3 pr-6">
                                                            <span className="text-zinc-200 font-medium">{s.strategy_name}</span>
                                                            {s.overfit_warning && <span className="ml-2 text-amber-500 text-xs">⚠</span>}
                                                        </td>
                                                        <td className={`py-3 pr-4 text-right font-mono font-medium ${s.win_rate_outsample > s.market_win_rate ? 'text-emerald-400' : 'text-rose-400'}`}>
                                                            {toPct(s.win_rate_outsample)}
                                                            <span className="text-zinc-600 text-xs ml-1">({toPct(s.market_win_rate)})</span>
                                                        </td>
                                                        <td className={`py-3 pr-4 text-right font-mono font-medium ${s.win_rate_outsample_hi > s.market_win_rate_hi ? 'text-emerald-400' : 'text-rose-400'}`}>
                                                            {toPct(s.win_rate_outsample_hi)}
                                                            <span className="text-zinc-600 text-xs ml-1">({toPct(s.market_win_rate_hi)})</span>
                                                        </td>
                                                        <td className={`py-3 pr-4 text-right font-mono font-medium ${s.loss_rate_outsample < s.market_loss_rate ? 'text-emerald-400' : 'text-rose-400'}`}>
                                                            {toPct(s.loss_rate_outsample)}
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
                                                                ? <span className="px-2 py-0.5 bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 rounded-full text-xs font-bold">顯著</span>
                                                                : <span className="px-2 py-0.5 bg-zinc-800 text-zinc-500 rounded-full text-xs">不顯著</span>
                                                            }
                                                        </td>
                                                    </tr>
                                                    {selectedId === s.strategy_id && (
                                                        <tr>
                                                            <td colSpan={9} className="py-3 px-2">
                                                                <DetailPanel strategyId={s.strategy_id} onClose={() => setSelectedId(null)} />
                                                            </td>
                                                        </tr>
                                                    )}
                                                </React.Fragment>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        </>
                    )}
                </div>

                {/* ── Footer Disclaimer ─────────────────────────────────── */}
                <p className="text-zinc-600 text-xs text-center pb-2 leading-relaxed">
                    AlphaForge 為學習型工具，勝率為歷史統計參考，不構成投資建議。<br className="sm:hidden" />
                    Bonferroni 校正門檻：p &lt; {result?.bonferroni_threshold.toFixed(4) ?? '…'}（各持有期獨立校正）
                </p>
            </div>
        </>
    )
}

export default StrategyPage
