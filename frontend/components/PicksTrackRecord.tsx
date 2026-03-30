// frontend/components/PicksTrackRecord.tsx
import { useState, useEffect } from 'react'
import api from '../lib/api'

interface ConcludedPick {
    pick_date: string
    stock_id: string
    stock_name: string
    entry_price: number
    exit_reason: 'take_profit' | 'stop_loss' | 'time_limit' | 'settled'
    return_pct: number
    days_held: number
    time_dimension: string
    buy_reasons: string[]
    take_profit_pct: number
    stop_loss_pct: number
    hold_days_max: number
}

interface LivePerf {
    trade_count: number
    win_rate: number | null
    avg_return: number | null
}

const EXIT_LABEL: Record<string, string> = {
    take_profit: '停利',
    stop_loss: '停損',
    time_limit: '到期',
    settled: '到期',
}

export default function PicksTrackRecord() {
    const [open, setOpen] = useState(false)
    const [livePerf, setLivePerf] = useState<LivePerf | null>(null)
    const [picks, setPicks] = useState<ConcludedPick[]>([])
    const [total, setTotal] = useState(0)
    const [offset, setOffset] = useState(0)
    const [loading, setLoading] = useState(false)
    const [expandedId, setExpandedId] = useState<string | null>(null)

    useEffect(() => {
        api.get('/strategy-miner/picks/live-performance')
            .then(r => setLivePerf(r.data))
            .catch(() => {})
    }, [])

    const load = async (newOffset: number) => {
        setLoading(true)
        try {
            const res = await api.get(
                `/strategy-miner/picks/concluded?limit=20&offset=${newOffset}`
            )
            if (newOffset === 0) {
                setPicks(res.data.items)
            } else {
                setPicks(prev => [...prev, ...res.data.items])
            }
            setTotal(res.data.total)
            setOffset(newOffset + 20)
        } finally {
            setLoading(false)
        }
    }

    const handleToggle = () => {
        setOpen(v => !v)
        if (!open && picks.length === 0) load(0)
    }

    const returnColor = (item: ConcludedPick) => {
        if (item.return_pct > 0) return 'text-rose-400'
        if (item.return_pct < 0) return 'text-emerald-400'
        return 'text-zinc-400'
    }

    const exitBadgeStyle = (reason: string) => {
        if (reason === 'take_profit')
            return 'bg-rose-900/40 text-rose-400 border-rose-800/50'
        if (reason === 'stop_loss')
            return 'bg-emerald-900/40 text-emerald-400 border-emerald-800/50'
        return 'bg-zinc-800/60 text-zinc-400 border-zinc-700/50'
    }

    const exitSymbol = (reason: string) =>
        reason === 'take_profit' ? ' ✓' : reason === 'stop_loss' ? ' ✗' : ''

    const tradeCount = livePerf?.trade_count ?? 0
    const winRate =
        livePerf?.win_rate != null
            ? `${(livePerf.win_rate * 100).toFixed(1)}%`
            : '—'
    const avgReturn =
        livePerf?.avg_return != null
            ? `${livePerf.avg_return > 0 ? '+' : ''}${livePerf.avg_return.toFixed(1)}%`
            : '—'

    return (
        <div className="bg-zinc-900/60 border border-zinc-800 rounded-2xl overflow-hidden">
            {/* ── Header ── */}
            <button
                onClick={handleToggle}
                className="w-full flex items-center justify-between px-4 py-3 hover:bg-zinc-800/40 transition-colors"
            >
                <div className="flex items-center gap-2">
                    <span className="text-xs font-bold text-zinc-400 uppercase tracking-widest">
                        歷史推薦成績
                    </span>
                    {tradeCount > 0 && (
                        <span className="text-[10px] font-mono text-zinc-500">
                            {tradeCount} 筆 · 勝率 {winRate} · 均 {avgReturn}
                        </span>
                    )}
                </div>
                <svg
                    viewBox="0 0 24 24"
                    width={14}
                    height={14}
                    className={`fill-zinc-500 transition-transform ${open ? 'rotate-180' : ''}`}
                >
                    <path d="M7,10L12,15L17,10H7Z" />
                </svg>
            </button>

            {/* ── Table ── */}
            {open && (
                <div className="border-t border-zinc-800">
                    {loading && picks.length === 0 && (
                        <div className="p-4 text-zinc-500 text-sm text-center">載入中...</div>
                    )}
                    {!loading && picks.length === 0 && (
                        <div className="p-4 text-zinc-500 text-sm text-center">
                            尚無已出場記錄
                        </div>
                    )}

                    {picks.map(item => {
                        const rowId = `${item.pick_date}-${item.stock_id}`
                        const isExpanded = expandedId === rowId
                        return (
                            <div
                                key={rowId}
                                className="border-b border-zinc-800/60 last:border-0"
                            >
                                {/* ── Row ── */}
                                <button
                                    onClick={() =>
                                        setExpandedId(isExpanded ? null : rowId)
                                    }
                                    className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-zinc-800/30 transition-colors text-left"
                                >
                                    <div className="flex items-center gap-3 min-w-0">
                                        <span className="text-[10px] font-mono text-zinc-600 shrink-0">
                                            {item.pick_date.slice(5)}
                                        </span>
                                        <span className="text-sm text-zinc-200 truncate">
                                            {item.stock_name}
                                        </span>
                                        <span
                                            className={`text-[10px] px-1.5 py-0.5 rounded border shrink-0 ${exitBadgeStyle(item.exit_reason)}`}
                                        >
                                            {EXIT_LABEL[item.exit_reason]}
                                            {exitSymbol(item.exit_reason)}
                                        </span>
                                    </div>
                                    <span
                                        className={`text-sm font-mono font-bold shrink-0 ${returnColor(item)}`}
                                    >
                                        {item.return_pct > 0 ? '+' : ''}
                                        {item.return_pct.toFixed(1)}%
                                    </span>
                                </button>

                                {/* ── Expanded Detail ── */}
                                {isExpanded && (
                                    <div className="px-4 pb-3 bg-zinc-900/40 text-xs text-zinc-400 space-y-1.5">
                                        <div className="flex gap-3 flex-wrap">
                                            <span>
                                                入場{' '}
                                                <span className="text-zinc-200">
                                                    {item.entry_price.toFixed(1)}
                                                </span>
                                            </span>
                                            <span>
                                                持有{' '}
                                                <span className="text-zinc-200">
                                                    {item.days_held}
                                                </span>{' '}
                                                天
                                            </span>
                                            <span className="text-zinc-600">
                                                {item.time_dimension} 維度
                                            </span>
                                        </div>
                                        <div className="text-zinc-600">
                                            停利 +{(item.take_profit_pct * 100).toFixed(0)}% ／ 停損 -
                                            {(item.stop_loss_pct * 100).toFixed(0)}% ／ 最多{' '}
                                            {item.hold_days_max} 天
                                        </div>
                                        {item.buy_reasons.length > 0 && (
                                            <div className="flex flex-wrap gap-1 pt-0.5">
                                                {item.buy_reasons.map((r) => (
                                                    <span
                                                        key={r}
                                                        className="bg-zinc-800 text-zinc-400 px-1.5 py-0.5 rounded text-[10px]"
                                                    >
                                                        {r}
                                                    </span>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                )}
                            </div>
                        )
                    })}

                    {/* ── 顯示更多 ── */}
                    {picks.length < total && (
                        <button
                            onClick={() => load(offset)}
                            disabled={loading}
                            className="w-full py-2.5 text-xs text-zinc-500 hover:text-zinc-300 transition-colors disabled:opacity-50"
                        >
                            {loading
                                ? '載入中...'
                                : `顯示更多（${picks.length} / ${total}）`}
                        </button>
                    )}
                </div>
            )}
        </div>
    )
}
