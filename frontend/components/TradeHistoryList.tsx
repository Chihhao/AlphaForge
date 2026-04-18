import React, { useState } from 'react'

const DIM_LABEL: Record<string, string> = { '5d': '5日', '10d': '10日', '20d': '20日' }
const DIM_TABS = ['5d', '10d', '20d'] as const
const EXIT_LABEL: Record<string, string> = { take_profit: '停利', stop_loss: '停損', time_limit: '到期' }

export interface TradeItem {
  entry_date: string
  exit_date: string | null
  return_pct: number
  exit_reason: string
  direction: string
  time_dimension: string
}

interface Props {
  trades: TradeItem[]
  defaultDim?: string
  maxVisible?: number       // 可視筆數上限（超過可捲動），預設 8
  showList?: boolean         // 是否顯示明細列表（undefined = 永遠顯示）
}

const fmtDate = (d: string) => { const p = d.split('-'); return `${parseInt(p[1])}/${p[2]}` }

export default function TradeHistoryList({ trades, defaultDim = '20d', maxVisible = 8, showList }: Props) {
  const [dimTab, setDimTab] = useState(defaultDim)

  const filtered = trades.filter(t => t.time_dimension === dimTab)
  const listVisible = showList !== false

  return (
    <>
      {/* 天數分頁 tab */}
      <div className="flex gap-1.5 mb-3">
        {DIM_TABS.map(tab => {
          const tabCount = trades.filter(t => t.time_dimension === tab).length
          if (tabCount === 0) return null
          return (
            <button
              key={tab}
              onClick={() => setDimTab(tab)}
              className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                dimTab === tab
                  ? 'bg-amber-500/20 text-amber-400 border border-amber-500/40'
                  : 'bg-zinc-800/60 text-zinc-400 border border-zinc-700/40 hover:text-zinc-300'
              }`}
            >
              {DIM_LABEL[tab]} ({tabCount}筆)
            </button>
          )
        })}
      </div>

      {filtered.length === 0 && (
        <p className="text-sm text-zinc-500">
          此股尚無真實推薦結案紀錄
        </p>
      )}

      {/* 逐筆明細（可捲動） */}
      {listVisible && filtered.length > 0 && (
        <div
          className="space-y-1.5 mt-3 pt-3 border-t border-zinc-800/40 overflow-y-auto"
          style={{ maxHeight: `${maxVisible * 40}px` }}
        >
          {filtered.map((t, i) => {
            const retColor = t.return_pct >= 0 ? 'text-rose-400' : 'text-emerald-400'
            const retStr = `${t.return_pct >= 0 ? '+' : ''}${t.return_pct.toFixed(1)}%`
            const icon = t.return_pct > 0 ? '✅' : '❌'
            const reasonLabel = EXIT_LABEL[t.exit_reason] ?? t.exit_reason
            return (
              <div key={i} className="flex items-center justify-between py-1.5 border-b border-zinc-800/30 last:border-0">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-[10px] font-bold text-rose-400 bg-rose-500/10 border border-rose-500/25 rounded px-1.5 py-0.5 leading-none shrink-0">多</span>
                  <span className="text-xs text-zinc-200 bg-zinc-700 px-1.5 py-0.5 rounded font-mono shrink-0">
                    {DIM_LABEL[t.time_dimension] ?? t.time_dimension}
                  </span>
                  <span className="text-zinc-400 font-mono text-xs shrink-0">{fmtDate(t.entry_date)}</span>
                  <span className="text-zinc-500 text-xs shrink-0">→</span>
                  <span className="text-zinc-400 font-mono text-xs shrink-0">{t.exit_date ? fmtDate(t.exit_date) : '—'}</span>
                  <span className={`text-xs shrink-0 ${
                    t.exit_reason === 'take_profit' ? 'text-rose-400'
                    : t.exit_reason === 'stop_loss' ? 'text-emerald-400'
                    : 'text-zinc-500'
                  }`}>{reasonLabel}</span>
                </div>
                <div className="flex items-center gap-1.5 shrink-0 ml-2">
                  <span className={`font-mono text-sm font-bold ${retColor}`}>{retStr}</span>
                  <span className="text-xs">{icon}</span>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </>
  )
}
