import React, { useEffect, useState } from 'react'
import api from '../lib/api'

interface ETFRow {
  date: string
  net_flow: number
}

interface PCRData {
  latest_pcr: number | null
  latest_date: string | null
  history: Array<{ date: string; pcr: number }>
}

export default function MarketSentimentWidget() {
  const [etfRows, setEtfRows] = useState<ETFRow[]>([])
  const [etf878Rows, setEtf878Rows] = useState<ETFRow[]>([])
  const [etf6208Rows, setEtf6208Rows] = useState<ETFRow[]>([])
  const [pcrData, setPcrData] = useState<PCRData | null>(null)

  useEffect(() => {
    api.get('/market/etf-flows?etf_id=0050&days=14').then(r => setEtfRows(r.data ?? [])).catch(() => {})
    api.get('/market/etf-flows?etf_id=00878&days=14').then(r => setEtf878Rows(r.data ?? [])).catch(() => {})
    api.get('/market/etf-flows?etf_id=006208&days=14').then(r => setEtf6208Rows(r.data ?? [])).catch(() => {})
    api.get('/market/pcr?days=30').then(r => setPcrData(r.data)).catch(() => {})
  }, [])

  if (etfRows.length === 0 && etf878Rows.length === 0 && etf6208Rows.length === 0 && !pcrData?.latest_pcr) return null

  const etfRecent5 = etfRows.slice(-5)
  const etfNetSum = etfRecent5.reduce((s, r) => s + (r.net_flow ?? 0), 0)
  const etfMaxAbs = Math.max(...etfRows.map(r => Math.abs(r.net_flow ?? 0)), 1)

  const etf878Recent5 = etf878Rows.slice(-5)
  const etf878NetSum = etf878Recent5.reduce((s, r) => s + (r.net_flow ?? 0), 0)

  return (
    <div className="bg-zinc-900/60 border border-white/10 rounded-2xl px-4 py-3">
      <div className="flex gap-4">
        {/* 外資買賣 ETF 區塊 */}
        <div className="flex-1 min-w-0 space-y-2">
          {etfRows.length > 0 && (
            <div>
              <div className="flex items-center justify-between mb-1">
                <span className="text-zinc-300 text-[10px] uppercase tracking-widest font-bold">外資 0050</span>
                <span className={`font-mono text-xs font-bold ${etfNetSum > 0 ? 'text-rose-400' : etfNetSum < 0 ? 'text-emerald-400' : 'text-zinc-500'}`}>
                  {etfNetSum > 0 ? '+' : ''}{etfNetSum.toFixed(0)}張
                </span>
              </div>
              <div className="flex items-center gap-px h-5">
                {etfRows.map((r, i) => {
                  const pct = etfMaxAbs > 0 ? Math.min(Math.abs(r.net_flow ?? 0) / etfMaxAbs * 100, 100) : 0
                  const isBuy = (r.net_flow ?? 0) >= 0
                  return (
                    <div key={i} className="flex-1 flex flex-col items-center justify-center h-full">
                      <div
                        className={`w-full rounded-[1px] ${isBuy ? 'bg-rose-500' : 'bg-emerald-600'} ${i === etfRows.length - 1 ? 'opacity-100' : 'opacity-40'}`}
                        style={{ height: `${Math.max(pct * 0.8, 4)}%` }}
                        title={`${r.date.slice(5)} ${r.net_flow > 0 ? '+' : ''}${r.net_flow?.toFixed(0)}張`}
                      />
                    </div>
                  )
                })}
              </div>
            </div>
          )}
          {etf878Rows.length > 0 && (
            <div>
              <div className="flex items-center justify-between mb-1">
                <span className="text-zinc-300 text-[10px] uppercase tracking-widest font-bold">外資 00878</span>
                <span className={`font-mono text-xs font-bold ${etf878NetSum > 0 ? 'text-rose-400' : etf878NetSum < 0 ? 'text-emerald-400' : 'text-zinc-500'}`}>
                  {etf878NetSum > 0 ? '+' : ''}{etf878NetSum.toFixed(0)}張
                </span>
              </div>
              <div className="flex items-center gap-px h-5">
                {etf878Rows.map((r, i) => {
                  const maxAbs = Math.max(...etf878Rows.map(x => Math.abs(x.net_flow ?? 0)), 1)
                  const pct = Math.min(Math.abs(r.net_flow ?? 0) / maxAbs * 100, 100)
                  const isBuy = (r.net_flow ?? 0) >= 0
                  return (
                    <div key={i} className="flex-1 flex flex-col items-center justify-center h-full">
                      <div
                        className={`w-full rounded-[1px] ${isBuy ? 'bg-rose-500' : 'bg-emerald-600'} ${i === etf878Rows.length - 1 ? 'opacity-100' : 'opacity-40'}`}
                        style={{ height: `${Math.max(pct * 0.8, 4)}%` }}
                        title={`${r.date.slice(5)} ${r.net_flow > 0 ? '+' : ''}${r.net_flow?.toFixed(0)}張`}
                      />
                    </div>
                  )
                })}
              </div>
            </div>
          )}
          {etf6208Rows.length > 0 && (() => {
            const etf6208NetSum = etf6208Rows.slice(-5).reduce((s, r) => s + (r.net_flow ?? 0), 0)
            const maxAbs = Math.max(...etf6208Rows.map(x => Math.abs(x.net_flow ?? 0)), 1)
            return (
              <div>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-zinc-300 text-[10px] uppercase tracking-widest font-bold">外資 006208</span>
                  <span className={`font-mono text-xs font-bold ${etf6208NetSum > 0 ? 'text-rose-400' : etf6208NetSum < 0 ? 'text-emerald-400' : 'text-zinc-500'}`}>
                    {etf6208NetSum > 0 ? '+' : ''}{etf6208NetSum.toFixed(0)}張
                  </span>
                </div>
                <div className="flex items-center gap-px h-5">
                  {etf6208Rows.map((r, i) => {
                    const pct = Math.min(Math.abs(r.net_flow ?? 0) / maxAbs * 100, 100)
                    const isBuy = (r.net_flow ?? 0) >= 0
                    return (
                      <div key={i} className="flex-1 flex flex-col items-center justify-center h-full">
                        <div
                          className={`w-full rounded-[1px] ${isBuy ? 'bg-rose-500' : 'bg-emerald-600'} ${i === etf6208Rows.length - 1 ? 'opacity-100' : 'opacity-40'}`}
                          style={{ height: `${Math.max(pct * 0.8, 4)}%` }}
                          title={`${r.date.slice(5)} ${r.net_flow > 0 ? '+' : ''}${r.net_flow?.toFixed(0)}張`}
                        />
                      </div>
                    )
                  })}
                </div>
              </div>
            )
          })()}
        </div>

        {/* PCR 區塊 */}
        {pcrData?.latest_pcr != null && (
          <div className="shrink-0 w-20 flex flex-col items-center justify-center gap-1 border-l border-zinc-800/60 pl-4">
            <span className="text-zinc-400 text-[10px] uppercase tracking-widest font-bold">PCR</span>
            <span className={`text-xl font-bold font-mono leading-none ${
              pcrData.latest_pcr >= 1.3 ? 'text-emerald-400' :
              pcrData.latest_pcr >= 1.0 ? 'text-amber-400' :
              'text-rose-400'
            }`}>
              {pcrData.latest_pcr.toFixed(2)}
            </span>
            <span className={`text-[10px] font-semibold ${
              pcrData.latest_pcr >= 1.3 ? 'text-emerald-500/70' :
              pcrData.latest_pcr >= 1.0 ? 'text-amber-500/70' :
              'text-rose-500/70'
            }`}>
              {pcrData.latest_pcr >= 1.3 ? '恐慌偏高' : pcrData.latest_pcr >= 1.0 ? '中性偏空' : '樂觀偏多'}
            </span>
            <span className="text-zinc-500 text-[10px]">Put/Call</span>
          </div>
        )}
      </div>
    </div>
  )
}
