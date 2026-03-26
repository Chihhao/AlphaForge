import React, { useEffect, useState } from 'react'
import api from '../lib/api'

interface SectorItem {
  industry: string
  median_rs: number
  stock_count: number
}

interface SectorStrengthData {
  date: string | null
  top: SectorItem[]
  bottom: SectorItem[]
}

export default function SectorStrengthWidget() {
  const [data, setData] = useState<SectorStrengthData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get('/market/sector-strength')
      .then(r => {
        setData(r.data)
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="bg-zinc-900/60 border border-white/10 rounded-2xl px-4 py-3">
        <div className="flex justify-between items-center mb-3 pb-2 border-b border-zinc-800/40">
          <span className="text-amber-400 text-sm font-bold flex items-center gap-1.5">
            <svg viewBox="0 0 24 24" width={14} height={14} className="fill-current">
              <path d="M3,13H5V11H3V13M3,17H5V15H3V17M3,9H5V7H3V9M7,13H21V11H7V13M7,17H21V15H7V17M7,7V9H21V7H7Z" />
            </svg>
            產業輪動強弱
          </span>
        </div>
        <p className="text-xs text-zinc-500">載入中...</p>
      </div>
    )
  }

  if (!data || !data.date || (data.top.length === 0 && data.bottom.length === 0)) {
    return (
      <div className="bg-zinc-900/60 border border-white/10 rounded-2xl px-4 py-3">
        <div className="flex justify-between items-center mb-3 pb-2 border-b border-zinc-800/40">
          <span className="text-amber-400 text-sm font-bold flex items-center gap-1.5">
            <svg viewBox="0 0 24 24" width={14} height={14} className="fill-current">
              <path d="M3,13H5V11H3V13M3,17H5V15H3V17M3,9H5V7H3V9M7,13H21V11H7V13M7,17H21V15H7V17M7,7V9H21V7H7Z" />
            </svg>
            產業輪動強弱
          </span>
        </div>
        <p className="text-xs text-zinc-500">產業資料尚未就緒，請先執行特徵回補</p>
      </div>
    )
  }

  const formatRs = (val: number) => (val >= 0 ? `+${val.toFixed(1)}` : val.toFixed(1))

  return (
    <div className="bg-zinc-900/60 border border-white/10 rounded-2xl px-4 py-3">
      <div className="flex justify-between items-center mb-3 pb-2 border-b border-zinc-800/40">
        <span className="text-amber-400 text-sm font-bold flex items-center gap-1.5">
          <svg viewBox="0 0 24 24" width={14} height={14} className="fill-current">
            <path d="M3,13H5V11H3V13M3,17H5V15H3V17M3,9H5V7H3V9M7,13H21V11H7V13M7,17H21V15H7V17M7,7V9H21V7H7Z" />
          </svg>
          產業輪動強弱
        </span>
        <span className="text-zinc-400 text-[10px] font-mono font-normal">{data.date}</span>
      </div>

      <div className="grid grid-cols-2 gap-3">
        {/* 強勢產業 */}
        <div>
          <p className="text-xs text-emerald-400 font-medium mb-2">近20日漲幅居前</p>
          <div className="space-y-1">
            {data.top.map((item) => (
              <div key={item.industry} className="flex items-center justify-between">
                <span className="text-xs text-zinc-300 truncate max-w-[100px]">{item.industry}</span>
                <span className="text-xs font-mono text-emerald-400 ml-1">
                  {formatRs(item.median_rs)}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* 弱勢產業 */}
        <div>
          <p className="text-xs text-rose-400 font-medium mb-2">近20日漲幅居後</p>
          <div className="space-y-1">
            {data.bottom.map((item) => (
              <div key={item.industry} className="flex items-center justify-between">
                <span className="text-xs text-zinc-300 truncate max-w-[100px]">{item.industry}</span>
                <span className="text-xs font-mono text-rose-400 ml-1">
                  {formatRs(item.median_rs)}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
