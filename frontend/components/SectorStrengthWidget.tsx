import React, { useEffect, useState } from 'react'

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
    fetch('/api/market/sector-strength')
      .then(r => r.json())
      .then((json: SectorStrengthData) => {
        setData(json)
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="bg-zinc-800/60 rounded-xl p-4 border border-zinc-700/50">
        <h2 className="text-sm font-semibold text-zinc-400 mb-3">產業輪動強弱</h2>
        <p className="text-xs text-zinc-500">載入中...</p>
      </div>
    )
  }

  if (!data || !data.date || (data.top.length === 0 && data.bottom.length === 0)) {
    return (
      <div className="bg-zinc-800/60 rounded-xl p-4 border border-zinc-700/50">
        <h2 className="text-sm font-semibold text-zinc-400 mb-3">產業輪動強弱</h2>
        <p className="text-xs text-zinc-500">產業資料尚未就緒，請先執行特徵回補</p>
      </div>
    )
  }

  const formatRs = (val: number) => (val >= 0 ? `+${val.toFixed(1)}` : val.toFixed(1))

  return (
    <div className="bg-zinc-800/60 rounded-xl p-4 border border-zinc-700/50">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-zinc-200">產業輪動強弱</h2>
        <span className="text-xs text-zinc-500">{data.date}</span>
      </div>

      <div className="grid grid-cols-2 gap-3">
        {/* 強勢產業 */}
        <div>
          <p className="text-xs text-emerald-400 font-medium mb-2">強勢產業</p>
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
          <p className="text-xs text-rose-400 font-medium mb-2">弱勢產業</p>
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
