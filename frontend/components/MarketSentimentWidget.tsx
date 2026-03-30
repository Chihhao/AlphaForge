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

interface VIXData {
  latest_close: number | null
  latest_date: string | null
  prev_close: number | null
  history: Array<{ date: string; close: number }>
}

function TrendArrow({ current, previous }: { current: number; previous: number | null }) {
  if (previous == null) return null
  const diff = current - previous
  if (Math.abs(diff) < 0.01) return <span className="text-zinc-500">→</span>
  return diff > 0
    ? <span className="text-rose-400">↑</span>
    : <span className="text-emerald-400">↓</span>
}

function useSentimentLabel(pcr: number | null, vix: number | null) {
  const pcrLevel = pcr == null ? 0 : pcr >= 1.5 ? 2 : pcr >= 1.0 ? 1 : 0
  const vixLevel = vix == null ? 0 : vix >= 30 ? 2 : vix >= 20 ? 1 : 0
  const score = pcrLevel + vixLevel

  if (pcr == null && vix == null) return { text: '', color: '' }

  if (score >= 3) return { text: '市場恐慌，留意反彈機會', color: 'text-emerald-400' }
  if (score >= 2) return { text: '避險情緒升溫，謹慎操作', color: 'text-amber-400' }
  if (score >= 1) return { text: '市場情緒中性', color: 'text-zinc-400' }
  return { text: '市場樂觀，留意追高風險', color: 'text-rose-400' }
}

export default function MarketSentimentWidget() {
  const [etfRows, setEtfRows] = useState<ETFRow[]>([])
  const [etf878Rows, setEtf878Rows] = useState<ETFRow[]>([])
  const [etf6208Rows, setEtf6208Rows] = useState<ETFRow[]>([])
  const [pcrData, setPcrData] = useState<PCRData | null>(null)
  const [vixData, setVixData] = useState<VIXData | null>(null)

  useEffect(() => {
    api.get('/market/etf-flows?etf_id=0050&days=14').then(r => setEtfRows(r.data ?? [])).catch(() => {})
    api.get('/market/etf-flows?etf_id=00878&days=14').then(r => setEtf878Rows(r.data ?? [])).catch(() => {})
    api.get('/market/etf-flows?etf_id=006208&days=14').then(r => setEtf6208Rows(r.data ?? [])).catch(() => {})
    api.get('/market/pcr?days=30').then(r => setPcrData(r.data)).catch(() => {})
    api.get('/market/vix?days=30').then(r => setVixData(r.data)).catch(() => {})
  }, [])

  if (etfRows.length === 0 && etf878Rows.length === 0 && etf6208Rows.length === 0 && !pcrData?.latest_pcr && !vixData?.latest_close) return null

  const etfRecent5 = etfRows.slice(-5)
  const etfNetSum = etfRecent5.reduce((s, r) => s + (r.net_flow ?? 0), 0)
  const etfMaxAbs = Math.max(...etfRows.map(r => Math.abs(r.net_flow ?? 0)), 1)

  const etf878Recent5 = etf878Rows.slice(-5)
  const etf878NetSum = etf878Recent5.reduce((s, r) => s + (r.net_flow ?? 0), 0)

  // PCR 趨勢：取最近 2 筆比較
  const pcrHistory = pcrData?.history ?? []
  const pcrPrev = pcrHistory.length >= 2 ? pcrHistory[pcrHistory.length - 2].pcr : null

  const sentiment = useSentimentLabel(pcrData?.latest_pcr ?? null, vixData?.latest_close ?? null)

  return (
    <div className="bg-zinc-900/60 border border-white/10 rounded-2xl px-4 py-3">
      {/* 標題 + 副標題 */}
      <div className="mb-3">
        <div className="flex items-center justify-between">
          <span className="text-zinc-200 text-sm font-bold">市場情緒</span>
          {sentiment.text && (
            <span className={`text-xs font-medium ${sentiment.color}`}>{sentiment.text}</span>
          )}
        </div>
      </div>

      <div className="flex gap-4">
        {/* 外資買賣 ETF 區塊 */}
        <div className="flex-1 min-w-0 space-y-2">
          {etfRows.length > 0 && (
            <div>
              <div className="flex items-center justify-between mb-1">
                <span className="text-zinc-300 text-xs uppercase tracking-widest font-bold">外資 0050</span>
                <span className={`font-mono text-xs font-bold ${etfNetSum > 0 ? 'text-rose-400' : etfNetSum < 0 ? 'text-emerald-400' : 'text-zinc-500'}`}>
                  {etfNetSum > 0 ? '+' : ''}{Math.abs(etfNetSum) >= 1000 ? (etfNetSum < 0 ? '-' : '') + Math.abs(etfNetSum).toFixed(0).replace(/\B(?=(\d{3})+(?!\d))/g, ',') : etfNetSum.toFixed(0)} 張
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
                <span className="text-zinc-300 text-xs uppercase tracking-widest font-bold">外資 00878</span>
                <span className={`font-mono text-xs font-bold ${etf878NetSum > 0 ? 'text-rose-400' : etf878NetSum < 0 ? 'text-emerald-400' : 'text-zinc-500'}`}>
                  {etf878NetSum > 0 ? '+' : ''}{Math.abs(etf878NetSum) >= 1000 ? (etf878NetSum < 0 ? '-' : '') + Math.abs(etf878NetSum).toFixed(0).replace(/\B(?=(\d{3})+(?!\d))/g, ',') : etf878NetSum.toFixed(0)} 張
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
                  <span className="text-zinc-300 text-xs uppercase tracking-widest font-bold">外資 006208</span>
                  <span className={`font-mono text-xs font-bold ${etf6208NetSum > 0 ? 'text-rose-400' : etf6208NetSum < 0 ? 'text-emerald-400' : 'text-zinc-500'}`}>
                    {etf6208NetSum > 0 ? '+' : ''}{Math.abs(etf6208NetSum) >= 1000 ? (etf6208NetSum < 0 ? '-' : '') + Math.abs(etf6208NetSum).toFixed(0).replace(/\B(?=(\d{3})+(?!\d))/g, ',') : etf6208NetSum.toFixed(0)} 張
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

        {/* PCR + VIX 區塊 */}
        {(pcrData?.latest_pcr != null || vixData?.latest_close != null) && (
          <div className="shrink-0 w-28 flex flex-col items-center justify-center gap-2">
            {/* PCR */}
            {pcrData?.latest_pcr != null && (
              <div className="text-center">
                <div className="text-zinc-400 text-xs font-bold tracking-wider">PCR</div>
                <div className="flex items-center justify-center gap-1">
                  <span className={`text-2xl font-bold font-mono leading-none ${
                    pcrData.latest_pcr >= 1.3 ? 'text-emerald-400' :
                    pcrData.latest_pcr >= 1.0 ? 'text-amber-400' :
                    'text-rose-400'
                  }`}>
                    {pcrData.latest_pcr.toFixed(2)}
                  </span>
                  <TrendArrow current={pcrData.latest_pcr} previous={pcrPrev} />
                </div>
                <div className={`text-xs ${
                  pcrData.latest_pcr >= 1.3 ? 'text-emerald-500/70' :
                  pcrData.latest_pcr >= 1.0 ? 'text-amber-500/70' :
                  'text-rose-500/70'
                }`}>
                  {pcrData.latest_pcr >= 1.5 ? '恐慌' : pcrData.latest_pcr >= 1.3 ? '偏空' : pcrData.latest_pcr >= 1.0 ? '中性' : '偏多'}
                </div>
              </div>
            )}

            {/* VIX */}
            {vixData?.latest_close != null && (
              <div className="text-center">
                <div className="text-zinc-400 text-xs font-bold tracking-wider">VIX</div>
                <div className="flex items-center justify-center gap-1">
                  <span className={`text-2xl font-bold font-mono leading-none ${
                    vixData.latest_close >= 30 ? 'text-emerald-400' :
                    vixData.latest_close >= 20 ? 'text-amber-400' :
                    'text-rose-400'
                  }`}>
                    {vixData.latest_close.toFixed(1)}
                  </span>
                  <TrendArrow current={vixData.latest_close} previous={vixData.prev_close} />
                </div>
                <div className={`text-xs ${
                  vixData.latest_close >= 30 ? 'text-emerald-500/70' :
                  vixData.latest_close >= 20 ? 'text-amber-500/70' :
                  'text-rose-500/70'
                }`}>
                  {vixData.latest_close >= 30 ? '恐慌' : vixData.latest_close >= 20 ? '波動' : '平靜'}
                </div>
              </div>
            )}

          </div>
        )}
      </div>
    </div>
  )
}
