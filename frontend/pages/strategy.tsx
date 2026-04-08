import React, { useEffect, useState } from 'react'
import Head from 'next/head'
import Link from 'next/link'
import api from '../lib/api'
import { todayLabel } from '../lib/formatters'
import { useWatchlist } from '../lib/useWatchlist'
import {
    LineChart, Line, XAxis, YAxis, Tooltip,
    ResponsiveContainer, CartesianGrid, ReferenceLine
} from 'recharts'
import TradeHistoryList, { TradeItem } from '../components/TradeHistoryList'

// ─── 多維度推薦清單 ──────────────────────────────────────────────────────────

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

interface RecommendationTableData {
    dimensions: DimensionRecommendation[]
    last_trained: string
    train_period: string
    test_period: string
}

const DIM_NAMES: Record<string, string> = { '20d': '20d' }

// 將各維度推薦攤平成統一列表，每筆標記來源維度
interface FlatPick {
    stock_id: string
    stock_name: string
    dimension: string
    win_rate: number
    avg_return: number
    is_stable: boolean
}

function RecPickCard({ pick, rank, direction }: { pick: FlatPick; rank: number; direction: 'long' | 'short' }) {
    const isLong = direction === 'long'
    const dimLabel = DIM_NAMES[pick.dimension] ?? pick.dimension
    const badge = isLong ? '多' : '空'
    const badgeClass = isLong
        ? 'text-rose-400 bg-rose-500/10 border-rose-500/25'
        : 'text-emerald-400 bg-emerald-500/10 border-emerald-500/25'
    const wrColor = pick.win_rate >= 50 ? 'text-rose-400' : 'text-zinc-400'
    const retColor = pick.avg_return >= 0 ? 'text-rose-400' : 'text-emerald-400'

    return (
        <div className="bg-zinc-900/60 border border-zinc-800 rounded-2xl px-3 py-3">
            <div className="flex items-start gap-1.5">
                <span className="text-zinc-600 font-mono text-xs shrink-0 w-5 mt-1">#{rank}</span>
                <div className="flex-1 min-w-0 flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
                    <span className={`text-[10px] font-bold border rounded px-1.5 py-0.5 leading-none ${badgeClass}`}>{badge}</span>
                    <Link href={`/stock/${pick.stock_id}`} className="text-white font-bold text-xl leading-none hover:text-amber-300 transition-colors">
                        {pick.stock_name}
                    </Link>
                    <span className="text-zinc-500 text-sm">{pick.stock_id}</span>
                    {pick.is_stable && (
                        <span className="text-[10px] px-1 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20 shrink-0">穩定</span>
                    )}
                    <div className="w-full flex flex-wrap items-center gap-x-2 gap-y-0.5 mt-0.5">
                        <span className={`font-mono text-xs ${wrColor}`}>
                            {dimLabel}勝率 {pick.win_rate.toFixed(0)}%
                        </span>
                        <span className="text-zinc-700">|</span>
                        <span className={`font-mono text-xs ${retColor}`}>
                            預計報酬 {pick.avg_return >= 0 ? '+' : ''}{pick.avg_return.toFixed(1)}%
                        </span>
                    </div>
                </div>
            </div>
        </div>
    )
}

function RecommendationSection({ data }: { data: RecommendationTableData | null }) {
    if (!data || data.dimensions.length === 0) return null

    // 攤平：每個維度的 picks 加上維度標記
    const longPicks: FlatPick[] = []
    const shortPicks: FlatPick[] = []
    for (const dim of data.dimensions) {
        for (const p of dim.long_picks) {
            longPicks.push({
                stock_id: p.stock_id, stock_name: p.stock_name,
                dimension: dim.dimension,
                win_rate: dim.long_win_rate, avg_return: dim.long_avg_return,
                is_stable: p.is_stable,
            })
        }
        for (const p of dim.short_picks) {
            shortPicks.push({
                stock_id: p.stock_id, stock_name: p.stock_name,
                dimension: dim.dimension,
                win_rate: dim.short_win_rate, avg_return: dim.short_avg_return,
                is_stable: p.is_stable,
            })
        }
    }

    if (longPicks.length === 0 && shortPicks.length === 0) return null

    return (
        <>
            {longPicks.length > 0 && (
                <>
                    <div className="flex items-center gap-3 px-1">
                        <div className="flex items-center gap-1.5">
                            <span className="w-1.5 h-1.5 rounded-full bg-rose-400" />
                            <span className="text-sm font-semibold text-zinc-300">做多</span>
                        </div>
                        <span className="text-xs font-mono text-zinc-500">{longPicks.length} 檔</span>
                        <div className="flex-1 h-px bg-zinc-800" />
                    </div>
                    <div className="flex flex-col gap-2">
                        {longPicks.map((p, i) => (
                            <RecPickCard key={`${p.dimension}-${p.stock_id}`} pick={p} rank={i + 1} direction="long" />
                        ))}
                    </div>
                </>
            )}
            <div className="flex items-center gap-3 px-1 mt-2">
                <div className="flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                    <span className="text-sm font-semibold text-zinc-300">做空</span>
                </div>
                <div className="flex-1 h-px bg-zinc-800" />
            </div>
            <p className="text-zinc-500 text-xs px-1">目前無推薦</p>
        </>
    )
}

// ─── Strategy Miner API 回傳型別 ──────────────────────────────────────────────
interface StrategyMinerPick {
    pick_date: string
    stock_id: string
    stock_name: string
    strategy_ids: string      // JSON string
    weighted_score: number
    entry_price: number
    take_profit_pct: number   // decimal: 0.05 = 5%
    stop_loss_pct: number     // decimal: 0.03 = 3%
    hold_days_max: number
    time_dimension: string
    direction?: string        // 'long' / 'short'
    buy_reasons?: string[]    // 買入理由（策略名稱列表）
    stock_win_rate?: number | null    // 個股回測勝率（來自 strategy_miner_trades）
    stock_avg_return?: number | null  // 個股回測平均報酬（%）
    stock_trade_count?: number        // 個股交易筆數
    stock_best_dim?: string | null    // 最佳勝率維度
}


interface TradeRecord {
    strategy_id: string
    stock_id: string
    entry_date: string
    entry_price: number
    exit_date: string | null
    exit_price: number | null
    exit_reason: string   // take_profit / stop_loss / time_limit
    return_pct: number    // percentage e.g. 7.9
    hold_days: number
}

// StrategyPick: PickCard 內部使用（從 API 回傳轉換而來）
interface StrategyPick {
    stock_id: string
    stock_name: string
    entry_price: number
    take_profit_pct: number   // integer %: 5
    stop_loss_pct: number     // integer %: 3
    hold_days_max: number
    weighted_score: number
    time_dimension: string
    direction: string         // 'long' / 'short'
    dims?: string[]           // 出現的維度列表（多維共鳴時 length > 1）
    buy_reasons?: string[]    // 買入理由
    stock_win_rate?: number | null    // 個股回測勝率（來自 strategy_miner_trades）
    stock_avg_return?: number | null  // 個股回測平均報酬（%）
    stock_trade_count?: number        // 個股交易筆數
    stock_best_dim?: string | null    // 最佳勝率維度
    strategy_win_rate?: number | null  // 策略級勝率（fallback）
    strategy_avg_return?: number | null // 策略級預計報酬（fallback）
    current_price?: number | null     // 即時/收盤價
    change_percent?: number | null    // 漲跌幅 (%)
}

const DIM_LABEL: Record<string, string> = { '5d': '5d', '10d': '10d', '20d': '20d' }

const toStars = (score: number) => {
    const n = score >= 20 ? 5 : score >= 15 ? 4 : score >= 10 ? 3 : score >= 5 ? 2 : 1
    return '★'.repeat(n)
}

// ─── PickCard ─────────────────────────────────────────────────────────────────
const PickCard = ({ pick, rank }: { pick: StrategyPick; rank: number }) => {
    const [expanded, setExpanded] = useState(false)
    const [trades, setTrades] = useState<TradeRecord[]>([])
    const [tradesLoading, setTradesLoading] = useState(false)
    const { toggle, has } = useWatchlist()
    const watched = has(pick.stock_id)

    const handleExpand = () => {
        const next = !expanded
        setExpanded(next)
        if (next && trades.length === 0) {
            setTradesLoading(true)
            api.get(`/strategy-miner/trades/${pick.stock_id}`)
                .then(r => {
                    setTrades(r.data ?? [])
                    setTradesLoading(false)
                })
                .catch(() => setTradesLoading(false))
        }
    }

    return (
        <div className="bg-zinc-900/60 border border-zinc-800 rounded-2xl px-3 py-3 cursor-pointer select-none" onClick={handleExpand}>
            {/* Row 1: rank + name + id + badges | price */}
            <div className="flex items-start gap-1.5">
                <span className="text-zinc-600 font-mono text-xs shrink-0 w-5 mt-1">#{rank}</span>
                <div className="flex-1 min-w-0 flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
                    <span className={`text-[10px] font-bold rounded px-1.5 py-0.5 leading-none border ${
                        pick.direction === 'short'
                            ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/25'
                            : 'text-rose-400 bg-rose-500/10 border-rose-500/25'
                    }`}>{pick.direction === 'short' ? '空' : '多'}</span>
                    <Link href={`/stock/${pick.stock_id}`} className="text-white font-bold text-xl leading-none hover:text-amber-300 transition-colors">
                        {pick.stock_name}
                    </Link>
                    <span className="text-zinc-500 text-sm">{pick.stock_id}</span>
                    <button
                        onClick={e => { e.stopPropagation(); toggle(pick.stock_id, pick.stock_name) }}
                        title={watched ? '從觀察清單移除' : '加入觀察清單'}
                        className={`p-0.5 transition-colors ${watched ? 'text-amber-400' : 'text-zinc-600 hover:text-amber-400'}`}
                    >
                        <svg viewBox="0 0 24 24" width={14} height={14} className="fill-current">
                            <path d={watched
                                ? "M12,17.27L18.18,21L16.54,13.97L22,9.24L14.81,8.62L12,2L9.19,8.62L2,9.24L7.45,13.97L5.82,21L12,17.27Z"
                                : "M12,15.39L8.24,17.66L9.23,13.38L5.91,10.5L10.29,10.13L12,6.09L13.71,10.13L18.09,10.5L14.77,13.38L15.76,17.66M22,9.24L14.81,8.62L12,2L9.19,8.62L2,9.24L7.45,13.97L5.82,21L12,17.27L18.18,21L16.54,13.97L22,9.24Z"
                            } />
                        </svg>
                    </button>
                    {pick.dims && pick.dims.length > 1 && (
                        <span className="text-[9px] font-bold text-cyan-400 bg-cyan-500/10 border border-cyan-500/25 rounded px-1 py-0.5 leading-none whitespace-nowrap">
                            多維
                        </span>
                    )}
                    {pick.stock_win_rate != null && (pick.stock_win_rate < 0.3 || (pick.stock_avg_return ?? 0) < -3) && (
                        <span title="此股歷史回測績效偏弱，謹慎參考" className="text-[9px] font-bold text-amber-500 bg-amber-500/10 border border-amber-500/25 rounded px-1 py-0.5 leading-none whitespace-nowrap">
                            ⚠ 績效偏弱
                        </span>
                    )}
                    {(() => {
                        const wr = pick.stock_win_rate ?? pick.strategy_win_rate
                        const ret = pick.stock_avg_return ?? pick.strategy_avg_return
                        const dim = pick.stock_best_dim ?? pick.time_dimension
                        const isStrategy = pick.stock_win_rate == null
                        if (wr == null) return null
                        return (
                            <div className="w-full flex flex-wrap items-center gap-x-2 gap-y-0.5 text-sm text-zinc-500 mt-0.5">
                                <span className={`font-mono text-xs ${wr >= 0.5 ? 'text-rose-400' : 'text-zinc-400'}`}>
                                    {DIM_LABEL[dim] ?? dim}{isStrategy ? '策略' : ''}勝率 {(wr * 100).toFixed(0)}%
                                </span>
                                {ret != null && (
                                    <>
                                        <span className="text-zinc-700">|</span>
                                        <span className={`font-mono text-xs ${ret >= 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                                            預計報酬 {ret >= 0 ? '+' : ''}{ret.toFixed(1)}%
                                        </span>
                                    </>
                                )}
                            </div>
                        )
                    })()}
                </div>
                {pick.current_price != null && pick.current_price > 0 && (
                    <div className="flex flex-col items-end shrink-0">
                        <span className="text-white font-mono font-bold text-lg leading-tight">{pick.current_price.toLocaleString()}</span>
                        {pick.change_percent != null && (
                            <span className={`font-mono text-xs font-bold leading-tight ${pick.change_percent >= 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                                {pick.change_percent >= 0 ? '▲' : '▼'} {pick.change_percent >= 0 ? '+' : ''}{pick.change_percent.toFixed(2)}%
                            </span>
                        )}
                    </div>
                )}
            </div>

            {/* Expanded */}
            {expanded && (
                <div className="mt-3 border-t border-zinc-800 pt-3" onClick={e => e.stopPropagation()}>
                    {/* 買入理由 tagline */}
                    {pick.buy_reasons && pick.buy_reasons.length > 0 && (() => {
                        const factorTags = pick.buy_reasons.filter(r => !r.includes('個策略共同'))
                        const countTag = pick.buy_reasons.find(r => r.includes('個策略共同'))
                        return (
                            <div className="flex flex-wrap items-center gap-1 mb-3">
                                {countTag && (() => {
                                    const m = countTag.match(/(\d+)\s*個策略/)
                                    return m ? (
                                        <span className="text-[10px] font-semibold text-zinc-500 shrink-0">{m[1]} 個策略共振</span>
                                    ) : null
                                })()}
                                {factorTags.map((r, i) => (
                                    <span key={i} className="text-[10px] font-medium text-amber-400/80 bg-amber-500/10 border border-amber-500/20 rounded-full px-2 py-0.5 leading-none whitespace-nowrap">
                                        {r}
                                    </span>
                                ))}
                            </div>
                        )
                    })()}
                    {tradesLoading && <p className="text-zinc-600 text-xs">載入中…</p>}

                    {!tradesLoading && trades.length === 0 && (
                        <p className="text-zinc-600 text-xs">此股票目前無歷史回測交易記錄（需先執行參數尋優）</p>
                    )}

                    {!tradesLoading && trades.length > 0 && (
                        <TradeHistoryList
                            trades={trades.map(t => ({
                                entry_date: t.entry_date,
                                exit_date: t.exit_date,
                                return_pct: t.return_pct,
                                exit_reason: t.exit_reason,
                                direction: 'long',
                                time_dimension: t.strategy_id,
                            }))}
                            defaultDim={pick.stock_best_dim || pick.time_dimension || '20d'}
                        />
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
    etf_net_flow_5d: 'ETF 5日淨申購資金流',
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

type DimKey = '20d'
const DIM_CONFIG: Record<DimKey, { label: string; shortLabel: string; desc: string }> = {
    '20d': { label: '20日持有', shortLabel: '20日', desc: '門檻 3% / 5%' },
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
            <p className={val >= 0 ? 'text-rose-400 font-bold' : 'text-emerald-400 font-bold'}>
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
                                    <div className="flex justify-between items-baseline">
                                        <span className="text-zinc-400 text-xs">賠率比</span>
                                        <span className={`text-base font-bold font-mono ${col.oddsVal >= 1.2 ? 'text-amber-400' : col.oddsVal >= 1.0 ? 'text-zinc-200' : 'text-rose-400'}`}>
                                            {col.oddsVal.toFixed(2)}x
                                        </span>
                                    </div>
                                    <div className="flex justify-between items-baseline">
                                        <span className="text-zinc-400 text-xs">策略 勝率</span>
                                        <span className={`text-base font-bold font-mono ${col.winStrat > col.winMkt ? 'text-rose-400' : 'text-emerald-400'}`}>{toPct(col.winStrat)}</span>
                                    </div>
                                    <div className="flex justify-between items-baseline">
                                        <span className="text-zinc-500 text-xs">市場 勝率</span>
                                        <span className="text-base font-bold font-mono text-zinc-500">{toPct(col.winMkt)}</span>
                                    </div>
                                    <div className="flex justify-between items-baseline">
                                        <span className="text-zinc-400 text-xs">策略 踩雷</span>
                                        {col.lossStrat > 0 || i === 0
                                            ? <span className={`text-base font-bold font-mono ${col.lossStrat < col.lossMkt ? 'text-rose-400' : 'text-emerald-400'}`}>{toPct(col.lossStrat)}</span>
                                            : <span className="text-zinc-700 text-base font-bold font-mono">—</span>
                                        }
                                    </div>
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
                            <span className={`text-base font-bold font-mono ${winLo > s.market_win_rate ? 'text-rose-400' : 'text-emerald-400'}`}>
                                {toPct(winLo)}
                            </span>
                        </div>
                        <div className="flex justify-between items-baseline">
                            <span className="text-zinc-400 text-xs">&lt;-{tlo}% 踩雷</span>
                            <span className={`text-base font-bold font-mono ${loss < s.market_loss_rate ? 'text-rose-400' : 'text-emerald-400'}`}>
                                {toPct(loss)}
                            </span>
                        </div>
                    </div>
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
                            <span className={`text-base font-bold font-mono ${winHi > s.market_win_rate_hi ? 'text-rose-400' : 'text-emerald-400'}`}>
                                {toPct(winHi)}
                            </span>
                        </div>
                        <div className="flex justify-between items-baseline">
                            <span className="text-zinc-400 text-xs">&lt;-{thi}% 踩雷</span>
                            <span className={`text-base font-bold font-mono ${s.loss_rate_outsample_hi < s.market_loss_rate_hi ? 'text-rose-400' : 'text-emerald-400'}`}>
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
    const [usingFallback, setUsingFallback] = useState(false)

    const [nextTradingDay, setNextTradingDay] = useState<string | null>(null)

    // 取得下一交易日（根據 pick_date 計算，而非今天）
    useEffect(() => {
        if (!signalDate) return
        api.get<{ label: string }>(`/market/next-trading-day?from_date=${signalDate}`)
            .then(r => { if (r.data?.label) setNextTradingDay(r.data.label) })
            .catch(() => {})
    }, [signalDate])

    const [alphaExpanded, setAlphaExpanded] = useState(false)
    const [alphaData, setAlphaData] = useState<AlphaMinerResult | null>(null)
    const [alphaLoading, setAlphaLoading] = useState(false)
    const [activeDim, setActiveDim] = useState<DimKey>('20d')
    const [selectedStratId, setSelectedStratId] = useState<string | null>(null)

    // Strategy Miner 回測績效
    const [perfExpanded, setPerfExpanded] = useState(false)
    const [perfData, setPerfData] = useState<Record<string, any> | null>(null)
    const [perfLoading, setPerfLoading] = useState(false)

    // 近期精選歷史
    const [histExpanded, setHistExpanded] = useState(false)
    const [histPicks, setHistPicks] = useState<StrategyMinerPick[]>([])
    const [histLoading, setHistLoading] = useState(false)

    const handleHistExpand = () => {
        const next = !histExpanded
        setHistExpanded(next)
        if (next && histPicks.length === 0 && !histLoading) {
            setHistLoading(true)
            api.get('/strategy-miner/picks/history?days=14')
                .then(r => { setHistPicks(r.data ?? []); setHistLoading(false) })
                .catch(() => setHistLoading(false))
        }
    }

    const handlePerfExpand = () => {
        const next = !perfExpanded
        setPerfExpanded(next)
        if (next && !perfData && !perfLoading) {
            setPerfLoading(true)
            api.get('/strategy-miner/performance')
                .then(r => { setPerfData(r.data); setPerfLoading(false) })
                .catch(() => setPerfLoading(false))
        }
    }

    const handleAlphaExpand = () => {
        const next = !alphaExpanded
        setAlphaExpanded(next)
        if (next && !alphaData && !alphaLoading) {
            setAlphaLoading(true)
            api.get(`/alpha-miner/strategies?dimension=${activeDim}`)
                .then(r => { setAlphaData(r.data); setAlphaLoading(false) })
                .catch(() => setAlphaLoading(false))
        }
    }

    const handleDimChange = (dim: DimKey) => {
        setActiveDim(dim)
        setSelectedStratId(null)
        setAlphaLoading(true)
        api.get(`/alpha-miner/strategies?dimension=${dim}`)
            .then(r => { setAlphaData(r.data); setAlphaLoading(false) })
            .catch(() => setAlphaLoading(false))
    }

    const enrichWithQuotes = async (stockIds: string[]) => {
        const results = await Promise.allSettled(
            stockIds.map(id => api.get(`/stocks/${id}/quote`))
        )
        const quoteMap = new Map<string, { price: number; change: number }>()
        results.forEach((r, i) => {
            if (r.status === 'fulfilled' && r.value.data) {
                quoteMap.set(stockIds[i], {
                    price: r.value.data.current_price ?? 0,
                    change: r.value.data.change_percent ?? 0,
                })
            }
        })
        setPicks(prev => prev.map(p => {
            const q = quoteMap.get(p.stock_id)
            return q ? { ...p, current_price: q.price, change_percent: q.change } : p
        }))
    }

    useEffect(() => {
        const loadPicks = async () => {
            try {
                // 同時載入 Strategy Miner + 推薦清單
                const [picksRes, stratRes] = await Promise.all([
                    api.get('/strategy-miner/picks/today'),
                    api.get<{ strategies: Array<{ strategy_id: string; win_rate_positive: number; avg_return_top: number; short_win_rate?: number; avg_return_bottom?: number }> }>('/alpha-miner/strategies').catch(() => ({ data: { strategies: [] } })),
                ])
                const data: StrategyMinerPick[] = picksRes.data ?? []

                // 建立策略級 lookup
                const stratMap: Record<string, { wr: number; avg: number }> = {}
                for (const s of stratRes.data?.strategies ?? []) {
                    stratMap[s.strategy_id] = { wr: s.win_rate_positive, avg: s.avg_return_top }
                }

                const VALID_DIMS = new Set(['20d'])
                const cleanDim = (d: string | null | undefined) => (d && VALID_DIMS.has(d)) ? d : null

                const minerPicks: StrategyPick[] = data
                    .filter(p => VALID_DIMS.has(p.time_dimension))
                    .map(p => {
                    const dim = p.time_dimension
                    const dimKey = `lgb_${dim}`
                    const strat = stratMap[dimKey]
                    return {
                        stock_id: p.stock_id,
                        stock_name: p.stock_name,
                        entry_price: p.entry_price,
                        take_profit_pct: Math.round(p.take_profit_pct * 100),
                        stop_loss_pct: Math.round(p.stop_loss_pct * 100),
                        hold_days_max: p.hold_days_max,
                        weighted_score: p.weighted_score,
                        time_dimension: dim,
                        direction: p.direction || 'long',
                        dims: (() => { try { return JSON.parse(p.strategy_ids).filter((d: string) => VALID_DIMS.has(d)) } catch { return [dim] } })(),
                        buy_reasons: p.buy_reasons ?? [],
                        stock_win_rate: p.stock_win_rate ?? null,
                        stock_avg_return: p.stock_avg_return != null ? p.stock_avg_return : null,
                        stock_trade_count: p.stock_trade_count ?? 0,
                        stock_best_dim: cleanDim(p.stock_best_dim) ?? dim,
                        strategy_win_rate: strat?.wr ?? null,
                        strategy_avg_return: strat?.avg ?? null,
                    }
                })

                const combined = minerPicks
                if (combined.length > 0) {
                    setSignalDate(data[0]?.pick_date ?? '')
                    // 按勝率排序：做多用正報酬勝率，做空用負報酬勝率
                    combined.sort((a, b) => {
                        const wrA = a.stock_win_rate ?? a.strategy_win_rate ?? 0
                        const wrB = b.stock_win_rate ?? b.strategy_win_rate ?? 0
                        return wrB - wrA
                    })
                    setPicks(combined)
                    setLoading(false)
                    // 所有 picks 都載入即時報價
                    enrichWithQuotes(combined.map(p => p.stock_id))
                    return
                }

                // Fallback：都沒資料，使用 Alpha Miner 訊號
                setUsingFallback(true)
                await loadFallback()
            } catch {
                setUsingFallback(true)
                await loadFallback().catch(e => {
                    setError(e.message)
                    setLoading(false)
                })
            }
        }

        const THRESHOLDS: Record<string, { lo: number; hi: number }> = {
            '20d': { lo: 3, hi: 5 },
        }
        const DIM_DAYS: Record<string, number> = { '20d': 20 }

        const loadFallback = async () => {
            const r20 = await api.get('/alpha-miner/signals/history?days=2&dimension=20d')
            const all = [...(r20.data ?? [])]
            if (all.length === 0) { setLoading(false); return }

            const maxDate = all.reduce((m: string, s: any) => s.signal_date > m ? s.signal_date : m, '')
            const latest = all.filter((s: any) => s.signal_date === maxDate)
            setSignalDate(maxDate)

            const map = new Map<string, any>()
            for (const s of latest) {
                const ex = map.get(s.stock_id)
                if (!ex || s.trigger_count > ex.trigger_count) map.set(s.stock_id, s)
            }
            const signals = Array.from(map.values()).sort((a, b) => b.trigger_count - a.trigger_count)

            const priceResults = await Promise.allSettled(
                signals.map((s: any) => api.get(`/stocks/${s.stock_id}/quote`))
            )
            const combined: StrategyPick[] = signals.map((s: any, i: number) => {
                const pr = priceResults[i]
                const quoteData = pr.status === 'fulfilled' ? pr.value.data : null
                const price: number = quoteData?.current_price ?? 0
                const { lo, hi } = THRESHOLDS[s.time_dimension] ?? { lo: 3, hi: 5 }
                return {
                    stock_id: s.stock_id,
                    stock_name: s.stock_name,
                    entry_price: price,
                    take_profit_pct: hi,
                    stop_loss_pct: lo,
                    hold_days_max: DIM_DAYS[s.time_dimension] ?? 10,
                    weighted_score: s.trigger_count * (s.weighted_odds_ratio ?? 1),
                    time_dimension: s.time_dimension,
                    direction: 'long',
                    current_price: price || null,
                    change_percent: quoteData?.change_percent ?? null,
                }
            })
            setPicks(combined)
            setLoading(false)
        }

        loadPicks()

    }, [])

    const displayDate = signalDate
        ? new Date(signalDate).toLocaleDateString('zh-TW', { month: '2-digit', day: '2-digit' })
        : new Date().toLocaleDateString('zh-TW', { month: '2-digit', day: '2-digit' })

    return (
        <>
            <Head><title>每日精選 | AlphaForge</title></Head>
            <div className="min-h-[calc(100vh-64px)] flex flex-col gap-4 sm:gap-6 max-w-7xl mx-auto px-3 sm:px-6 lg:px-8 py-4 sm:py-8">

                {/* ── Header ───────────────────────────────────────────── */}
                <div className="relative overflow-hidden bg-zinc-900/40 border border-zinc-800/60 rounded-2xl sm:rounded-3xl px-4 py-4 sm:px-8 sm:py-6">
                    <div className="absolute top-0 right-0 w-48 h-48 sm:w-64 sm:h-64 bg-amber-500/5 rounded-full blur-3xl -mr-24 -mt-24 pointer-events-none" />
                    <div className="relative">
                        <div className="flex items-center justify-between mb-1">
                            <div className="flex items-center gap-3">
                                <svg viewBox="0 0 24 24" width="22" height="22" className="fill-amber-400 shrink-0">
                                    <path d="M16,6L18.29,8.29L13.42,13.17L9.42,9.17L2,16.59L3.41,18L9.42,12L13.42,16L19.71,9.71L22,12V6H16Z" />
                                </svg>
                                <h1 className="text-xl sm:text-2xl font-bold text-white tracking-tight">
                                    {nextTradingDay ?? todayLabel()} 操作建議
                                </h1>
                            </div>
                            <span className="text-zinc-500 text-xs font-mono">更新於{displayDate}</span>
                        </div>
                        <p className="text-zinc-500 text-sm leading-relaxed">
                            量化模型篩選 · 每日收盤後自動更新 · 不構成投資建議
                        </p>
                        {usingFallback && (
                            <p className="text-amber-600 text-xs mt-1">
                                ⚠ 回測參數尚未產生，停利/停損使用預設值
                            </p>
                        )}
                        {/* 操作流程提示 */}
                        <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-zinc-400">
                            <span className="flex items-center gap-1.5">
                                <span className="text-amber-500 font-bold">1</span>
                                <span>{nextTradingDay ?? todayLabel()} 開盤後以參考價附近買入</span>
                            </span>
                            <span className="text-zinc-800">·</span>
                            <span className="flex items-center gap-1.5">
                                <span className="text-amber-500 font-bold">2</span>
                                <span>達停利目標時賣出，跌破停損立即出場</span>
                            </span>
                            <span className="text-zinc-800">·</span>
                            <span className="flex items-center gap-1.5">
                                <span className="text-amber-500 font-bold">3</span>
                                <span>超過持有天數上限時出場</span>
                            </span>
                        </div>
                    </div>
                </div>

                {error && (
                    <div className="bg-rose-900/20 border border-rose-800/50 rounded-2xl p-4 text-rose-400 text-sm">
                        載入失敗：{error}
                    </div>
                )}

                {loading && (
                    <div className="flex flex-col gap-2">
                        {[1, 2, 3].map(i => (
                            <div key={i} className="bg-zinc-900/60 border border-zinc-800 rounded-2xl px-3 py-3 animate-pulse">
                                <div className="h-6 bg-zinc-800 rounded w-1/3 mb-2" />
                                <div className="h-4 bg-zinc-800 rounded w-2/3 mb-2" />
                                <div className="h-4 bg-zinc-800 rounded w-1/2" />
                            </div>
                        ))}
                    </div>
                )}
                {!loading && picks.length === 0 && !error && (
                    <div className="bg-zinc-900/40 border border-zinc-800/60 rounded-2xl p-8 text-center">
                        <p className="text-zinc-500 text-sm">{nextTradingDay ?? todayLabel()} 暫無訊號</p>
                        <p className="text-zinc-400 text-xs mt-1">模型尚未完成今日掃描，或今日無符合條件標的</p>
                    </div>
                )}
                {(() => {
                    const longPicks = picks.filter(p => p.direction === 'long').slice(0, 5)
                    const shortPicks = picks.filter(p => p.direction === 'short').slice(0, 5)
                    return !loading && (
                        <>
                            {longPicks.length > 0 && (
                                <>
                                    <div className="flex items-center gap-3 px-1">
                                        <div className="flex items-center gap-1.5">
                                            <span className="w-1.5 h-1.5 rounded-full bg-rose-400" />
                                            <span className="text-sm font-semibold text-zinc-300">做多</span>
                                        </div>
                                        <span className="text-xs font-mono text-zinc-500">{longPicks.length} 檔</span>
                                        <div className="flex-1 h-px bg-zinc-800" />
                                    </div>
                                    <div className="flex flex-col gap-2">
                                        {longPicks.map((pick, i) => (
                                            <PickCard key={pick.stock_id} pick={pick} rank={i + 1} />
                                        ))}
                                    </div>
                                </>
                            )}
                            <div className="flex items-center gap-3 px-1">
                                <div className="flex items-center gap-1.5">
                                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                                    <span className="text-sm font-semibold text-zinc-300">做空</span>
                                </div>
                                <div className="flex-1 h-px bg-zinc-800" />
                            </div>
                            <p className="text-zinc-500 text-xs px-1">目前無推薦</p>
                        </>
                    )
                })()}
                {/* ── 近期精選歷史（折疊）─────────────────────────────── */}
                <div className="border border-zinc-800/60 rounded-2xl overflow-hidden">
                    <button
                        onClick={handleHistExpand}
                        className="w-full flex items-center justify-between px-4 py-4 bg-zinc-900/40 hover:bg-zinc-800/40 transition-colors cursor-pointer"
                    >
                        <div className="flex items-center gap-2.5">
                            <svg viewBox="0 0 24 24" width="18" height="18" className="fill-zinc-500 shrink-0">
                                <path d="M9,11H7V13H9V11M13,11H11V13H13V11M17,11H15V13H17V11M19,3H18V1H16V3H8V1H6V3H5C3.89,3 3,3.9 3,5V19A2,2 0 0,0 5,21H19A2,2 0 0,0 21,19V5A2,2 0 0,0 19,3M19,19H5V8H19V19Z" />
                            </svg>
                            <span className="text-zinc-400 font-semibold text-sm">近期精選歷史</span>
                            {histPicks.length > 0 && (
                                <span className="text-zinc-600 text-xs font-mono">近 14 日</span>
                            )}
                        </div>
                        <span className="text-zinc-600 text-xs">{histExpanded ? '▲ 收起' : '▼ 展開'}</span>
                    </button>

                    {histExpanded && (
                        <div className="px-3 pb-3 pt-1">
                            {histLoading && (
                                <div className="space-y-1.5 py-2">
                                    {[1,2,3].map(i => <div key={i} className="h-8 bg-zinc-800/40 rounded animate-pulse" />)}
                                </div>
                            )}
                            {!histLoading && histPicks.length === 0 && (
                                <p className="text-zinc-600 text-sm text-center py-4">近 14 日無精選記錄</p>
                            )}
                            {!histLoading && histPicks.length > 0 && (() => {
                                // 按日期分組
                                const byDate = histPicks.reduce<Record<string, StrategyMinerPick[]>>((acc, p) => {
                                    ;(acc[p.pick_date] ??= []).push(p)
                                    return acc
                                }, {})
                                return (
                                    <div className="space-y-2 mt-1">
                                        {Object.entries(byDate)
                                            .sort(([a], [b]) => b.localeCompare(a))
                                            .map(([d, dayPicks]) => (
                                                <div key={d}>
                                                    <p className="text-zinc-600 text-[10px] font-mono px-1 mb-1">
                                                        {new Date(d).toLocaleDateString('zh-TW', { month: '2-digit', day: '2-digit' })}
                                                    </p>
                                                    <div className="flex flex-wrap gap-1.5">
                                                        {dayPicks.map(p => {
                                                            const days = p.time_dimension?.replace('d', '') || ''
                                                            const wr = p.stock_win_rate != null ? `${days}日勝率${Math.round(p.stock_win_rate * 100)}%` : null
                                                            const avg = p.stock_avg_return != null ? `${p.stock_avg_return > 0 ? '+' : ''}${p.stock_avg_return.toFixed(1)}%` : null
                                                            return (
                                                                <Link
                                                                    key={p.stock_id}
                                                                    href={`/stock/${p.stock_id}`}
                                                                    className="inline-flex items-center gap-1 px-2 py-1 bg-zinc-800/60 border border-zinc-700/50 rounded-lg text-xs hover:border-amber-500/50 hover:text-amber-300 transition-colors"
                                                                >
                                                                    <span className="font-bold text-[10px] text-rose-400">多</span>
                                                                    <span className="text-zinc-300 font-medium">{p.stock_name}</span>
                                                                    {wr && (
                                                                        <span className="text-zinc-500 font-mono">
                                                                            {wr}{avg ? ` | 預期報酬 ${avg}` : ''}
                                                                        </span>
                                                                    )}
                                                                </Link>
                                                            )
                                                        })}
                                                    </div>
                                                </div>
                                            ))}
                                    </div>
                                )
                            })()}
                        </div>
                    )}
                </div>

                {/* ── Strategy Miner 回測績效（折疊）─────────────────── */}
                <div className="border border-zinc-800/60 rounded-2xl overflow-hidden">
                    <button
                        onClick={handlePerfExpand}
                        className="w-full flex items-center justify-between px-4 py-4 bg-zinc-900/40 hover:bg-zinc-800/40 transition-colors cursor-pointer"
                    >
                        <div className="flex items-center gap-2.5">
                            <svg viewBox="0 0 24 24" width="18" height="18" className="fill-zinc-500 shrink-0">
                                <path d="M22,21H2V3H4V19H6V10H10V19H12V14H16V19H18V7H22V21Z" />
                            </svg>
                            <span className="text-zinc-400 font-semibold text-sm">Strategy Miner 回測績效</span>
                            {perfData && !perfLoading && (
                                <span className="text-zinc-600 text-xs font-mono">
                                    {Object.keys(perfData).length} 個維度已優化
                                </span>
                            )}
                        </div>
                        <span className="text-zinc-600 text-xs">{perfExpanded ? '▲ 收起' : '▼ 展開'}</span>
                    </button>

                    {perfExpanded && (
                        <div className="px-3 pb-4 pt-2 space-y-3">
                            {perfLoading && (
                                <div className="space-y-2">
                                    {[1, 2, 3].map(i => <div key={i} className="h-16 bg-zinc-800/40 rounded-xl animate-pulse" />)}
                                </div>
                            )}
                            {!perfLoading && perfData && Object.keys(perfData).length === 0 && (
                                <p className="text-zinc-600 text-sm text-center py-4">尚無回測資料（需先執行參數尋優）</p>
                            )}
                            {!perfLoading && perfData && Object.keys(perfData).length > 0 && (
                                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                                    {(['20d'] as const).map(dim => {
                                        const p = perfData[dim]
                                        if (!p) return null
                                        return (
                                            <div key={dim} className="bg-zinc-800/50 rounded-xl px-3 py-3 space-y-1.5">
                                                <div className="flex items-center justify-between mb-2">
                                                    <span className="text-zinc-300 font-semibold text-sm">{DIM_LABEL[dim] ?? dim}持有</span>
                                                    {p.computed_at && (
                                                        <span className="text-zinc-700 text-[10px] font-mono">{p.computed_at}</span>
                                                    )}
                                                </div>
                                                <div className="flex justify-between items-baseline">
                                                    <span className="text-zinc-500 text-xs">最優參數</span>
                                                    <span className="text-amber-400 font-mono text-xs font-bold">
                                                        +{Math.round(p.take_profit_pct * 100)}% / -{Math.round(p.stop_loss_pct * 100)}% / {p.hold_days_max}天
                                                    </span>
                                                </div>
                                                <div className="flex justify-between items-baseline">
                                                    <span className="text-zinc-500 text-xs">測試集 Sharpe</span>
                                                    <span className={`font-mono text-sm font-bold ${p.sharpe_test > 0.5 ? 'text-emerald-400' : p.sharpe_test > 0 ? 'text-zinc-300' : 'text-rose-400'}`}>
                                                        {p.sharpe_test?.toFixed(3) ?? '—'}
                                                    </span>
                                                </div>
                                                <div className="flex justify-between items-baseline">
                                                    <span className="text-zinc-500 text-xs">測試集勝率</span>
                                                    <span className={`font-mono text-sm font-bold ${(p.win_rate_test ?? 0) >= 0.5 ? 'text-rose-400' : 'text-zinc-400'}`}>
                                                        {p.win_rate_test ? `${(p.win_rate_test * 100).toFixed(1)}%` : '—'}
                                                    </span>
                                                </div>
                                                <div className="flex justify-between items-baseline">
                                                    <span className="text-zinc-500 text-xs">平均報酬</span>
                                                    <span className={`font-mono text-sm font-bold ${(p.avg_return_test ?? 0) >= 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                                                        {p.avg_return_test != null ? `${p.avg_return_test >= 0 ? '+' : ''}${p.avg_return_test.toFixed(2)}%` : '—'}
                                                    </span>
                                                </div>
                                                <div className="flex justify-between items-baseline">
                                                    <span className="text-zinc-500 text-xs">測試交易筆數</span>
                                                    <span className="font-mono text-sm text-zinc-400">{p.trade_count_test ?? '—'}</span>
                                                </div>
                                            </div>
                                        )
                                    })}
                                </div>
                            )}
                        </div>
                    )}
                </div>

                {/* ── Alpha Miner 策略庫（折疊）──────────────────────── */}
                <div className="border border-zinc-800/60 rounded-2xl overflow-hidden">
                    <button
                        onClick={handleAlphaExpand}
                        className="w-full flex items-center justify-between px-4 py-4 bg-zinc-900/40 hover:bg-zinc-800/40 transition-colors cursor-pointer"
                    >
                        <div className="flex items-center gap-2.5">
                            <svg viewBox="0 0 24 24" width="18" height="18" className="fill-zinc-500 shrink-0">
                                <path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-7 14l-5-5 1.41-1.41L12 14.17l7.59-7.59L21 8l-9 9z" />
                            </svg>
                            <span className="text-zinc-400 font-semibold text-sm">Alpha Miner 策略庫</span>
                            {alphaData && (
                                <span className="text-zinc-600 text-xs font-mono">
                                    {alphaData.strategies?.length ?? 0} 個顯著策略
                                </span>
                            )}
                        </div>
                        <span className="text-zinc-600 text-xs">{alphaExpanded ? '▲ 收起' : '▼ 展開'}</span>
                    </button>

                    {alphaExpanded && (
                        <div className="px-3 pb-3 pt-1 space-y-3">
                            {/* Dim tabs */}
                            <div className="flex gap-2 pt-1">
                                {(Object.keys(DIM_CONFIG) as DimKey[]).map(dim => (
                                    <button
                                        key={dim}
                                        onClick={() => handleDimChange(dim)}
                                        className={`px-4 py-1.5 rounded-xl text-sm font-medium transition-colors cursor-pointer ${
                                            activeDim === dim
                                                ? 'bg-zinc-700 text-zinc-100'
                                                : 'text-zinc-500 hover:text-zinc-300'
                                        }`}
                                    >
                                        {DIM_CONFIG[dim].shortLabel}
                                    </button>
                                ))}
                            </div>

                            {alphaLoading && (
                                <div className="space-y-2">
                                    {[1, 2, 3].map(i => (
                                        <div key={i} className="h-20 bg-zinc-800/40 rounded-xl animate-pulse" />
                                    ))}
                                </div>
                            )}

                            {!alphaLoading && alphaData && (() => {
                                const strategies = alphaData.strategies ?? []
                                const tloMap: Record<DimKey, number> = { '20d': 3 }
                                const thiMap: Record<DimKey, number> = { '20d': 5 }
                                const tlo = tloMap[activeDim]
                                const thi = thiMap[activeDim]
                                return (
                                    <>
                                        {strategies.length === 0 ? (
                                            <p className="text-zinc-600 text-sm text-center py-4">此維度暫無顯著策略</p>
                                        ) : (
                                            <div className="space-y-2">
                                                {strategies.map((s, idx) => (
                                                    <MobileCard
                                                        key={s.strategy_id}
                                                        s={s}
                                                        idx={idx}
                                                        tlo={tlo}
                                                        thi={thi}
                                                        dimLabel={DIM_CONFIG[activeDim].shortLabel}
                                                        isSelected={selectedStratId === s.strategy_id}
                                                        onToggle={() => setSelectedStratId(
                                                            selectedStratId === s.strategy_id ? null : s.strategy_id
                                                        )}
                                                    />
                                                ))}
                                            </div>
                                        )}
                                        {alphaData.last_trained && (
                                            <p className="text-zinc-700 text-xs text-right pt-1">
                                                模型訓練：{new Date(alphaData.last_trained).toLocaleDateString('zh-TW', { year: 'numeric', month: '2-digit', day: '2-digit' })}
                                                ・測試期：{alphaData.test_period}
                                                ・共測試 {alphaData.total_combinations_tested} 組合
                                            </p>
                                        )}
                                    </>
                                )
                            })()}
                        </div>
                    )}
                </div>

            </div>
        </>
    )
}

export default StrategyPage
