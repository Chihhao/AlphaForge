import React, { useEffect, useState } from 'react'
import api from '../lib/api'

interface PCRRow {
  date: string
  pcr: number
}

interface ETFRow {
  date: string
  net_flow: number
}

function MiniBar({ value, max, color }: { value: number; max: number; color: string }) {
  const pct = max > 0 ? Math.min(Math.abs(value) / max * 100, 100) : 0
  return (
    <div className="flex items-center justify-end gap-1 h-5">
      {value < 0 && (
        <div className={`h-2 rounded-sm ${color} opacity-50`} style={{ width: `${pct * 0.6}%`, minWidth: pct > 0 ? 2 : 0 }} />
      )}
      <div
        className={`h-2 rounded-sm ${value >= 0 ? color : 'bg-zinc-700'}`}
        style={{ width: `${pct * 0.6}%`, minWidth: pct > 0 ? 2 : 0 }}
      />
    </div>
  )
}

export default function MarketSentimentWidget() {
  const [pcrRows, setPcrRows] = useState<PCRRow[]>([])
  const [etfRows, setEtfRows] = useState<ETFRow[]>([])
  const [etf878Rows, setEtf878Rows] = useState<ETFRow[]>([])
  const [etf6208Rows, setEtf6208Rows] = useState<ETFRow[]>([])

  useEffect(() => {
    api.get('/market/pcr?days=14').then(r => setPcrRows(r.data ?? [])).catch(() => {})
    api.get('/market/etf-flows?etf_id=0050&days=14').then(r => setEtfRows(r.data ?? [])).catch(() => {})
    api.get('/market/etf-flows?etf_id=00878&days=14').then(r => setEtf878Rows(r.data ?? [])).catch(() => {})
    api.get('/market/etf-flows?etf_id=006208&days=14').then(r => setEtf6208Rows(r.data ?? [])).catch(() => {})
  }, [])

  if (pcrRows.length === 0 && etfRows.length === 0 && etf878Rows.length === 0 && etf6208Rows.length === 0) return null

  const latestPcr = pcrRows.length > 0 ? pcrRows[pcrRows.length - 1].pcr : null
  const pcrLabel = latestPcr == null ? '—'
    : latestPcr >= 1.5 ? '恐慌超賣'
    : latestPcr >= 1.0 ? '偏空'
    : latestPcr >= 0.8 ? '中性'
    : '偏多'
  const pcrColor = latestPcr == null ? 'text-zinc-500'
    : latestPcr >= 1.5 ? 'text-rose-400'
    : latestPcr >= 1.0 ? 'text-amber-400'
    : latestPcr >= 0.8 ? 'text-zinc-400'
    : 'text-emerald-400'

  const etfRecent5 = etfRows.slice(-5)
  const etfNetSum = etfRecent5.reduce((s, r) => s + (r.net_flow ?? 0), 0)
  const etfMaxAbs = Math.max(...etfRows.map(r => Math.abs(r.net_flow ?? 0)), 1)

  const etf878Recent5 = etf878Rows.slice(-5)
  const etf878NetSum = etf878Recent5.reduce((s, r) => s + (r.net_flow ?? 0), 0)

  return (
    <div className="bg-zinc-900/60 border border-white/10 rounded-2xl px-4 py-3 flex gap-4">
      {/* PCR 區塊 */}
      {pcrRows.length > 0 && (
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-zinc-500 text-[10px] uppercase tracking-widest font-bold">選擇權 PCR</span>
            <span className={`font-mono text-xs font-bold ${pcrColor}`}>
              {latestPcr != null ? latestPcr.toFixed(2) : '—'} · {pcrLabel}
            </span>
          </div>
          {pcrRows.length >= 3 ? (
            <div className="flex items-end gap-px h-8">
              {pcrRows.map((r, i) => {
                const h = Math.min(Math.max((r.pcr / 2) * 100, 8), 100)
                const isHigh = r.pcr >= 1.5
                const isMid = r.pcr >= 1.0
                const color = isHigh ? 'bg-rose-500' : isMid ? 'bg-amber-500' : r.pcr >= 0.8 ? 'bg-zinc-500' : 'bg-emerald-500'
                return (
                  <div
                    key={i}
                    className={`flex-1 rounded-[1px] ${color} ${i === pcrRows.length - 1 ? 'opacity-100' : 'opacity-50'}`}
                    style={{ height: `${h}%` }}
                    title={`${r.date.slice(5)} PCR: ${r.pcr.toFixed(2)}`}
                  />
                )
              })}
            </div>
          ) : (
            <div className="flex items-center h-8 gap-2">
              <span className={`font-mono text-2xl font-bold ${pcrColor}`}>
                {latestPcr != null ? latestPcr.toFixed(2) : '—'}
              </span>
              {pcrRows.length === 2 && (() => {
                const prev = pcrRows[0].pcr
                const curr = pcrRows[1].pcr
                const up = curr > prev
                const same = curr === prev
                return (
                  <span className={`text-sm font-bold ${up ? 'text-rose-400' : same ? 'text-zinc-500' : 'text-emerald-400'}`}>
                    {up ? '↑' : same ? '→' : '↓'}
                  </span>
                )
              })()}
              <span className="text-zinc-600 text-xs">資料累積中</span>
            </div>
          )}
        </div>
      )}

      {(pcrRows.length > 0) && (etfRows.length > 0 || etf878Rows.length > 0 || etf6208Rows.length > 0) && (
        <div className="w-px bg-zinc-800 self-stretch" />
      )}

      {/* 外資買賣 ETF 區塊 */}
      {(etfRows.length > 0 || etf878Rows.length > 0 || etf6208Rows.length > 0) && (
        <div className="flex-1 min-w-0 space-y-2">
          {etfRows.length > 0 && (
            <div>
              <div className="flex items-center justify-between mb-1">
                <span className="text-zinc-500 text-[10px] uppercase tracking-widest font-bold">外資 0050</span>
                <span className={`font-mono text-xs font-bold ${etfNetSum > 0 ? 'text-emerald-400' : etfNetSum < 0 ? 'text-rose-400' : 'text-zinc-500'}`}>
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
                        className={`w-full rounded-[1px] ${isBuy ? 'bg-emerald-600' : 'bg-rose-500'} ${i === etfRows.length - 1 ? 'opacity-100' : 'opacity-40'}`}
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
                <span className="text-zinc-500 text-[10px] uppercase tracking-widest font-bold">外資 00878</span>
                <span className={`font-mono text-xs font-bold ${etf878NetSum > 0 ? 'text-emerald-400' : etf878NetSum < 0 ? 'text-rose-400' : 'text-zinc-500'}`}>
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
                        className={`w-full rounded-[1px] ${isBuy ? 'bg-emerald-600' : 'bg-rose-500'} ${i === etf878Rows.length - 1 ? 'opacity-100' : 'opacity-40'}`}
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
                  <span className="text-zinc-500 text-[10px] uppercase tracking-widest font-bold">外資 006208</span>
                  <span className={`font-mono text-xs font-bold ${etf6208NetSum > 0 ? 'text-emerald-400' : etf6208NetSum < 0 ? 'text-rose-400' : 'text-zinc-500'}`}>
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
                          className={`w-full rounded-[1px] ${isBuy ? 'bg-emerald-600' : 'bg-rose-500'} ${i === etf6208Rows.length - 1 ? 'opacity-100' : 'opacity-40'}`}
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
      )}
    </div>
  )
}
