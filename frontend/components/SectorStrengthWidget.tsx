import React, { useEffect, useState, useCallback } from 'react'
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

interface SectorStockItem {
  stock_id: string
  name: string
  ret20: number
}

const SectorIcon = () => (
  <svg viewBox="0 0 24 24" width={14} height={14} className="fill-current">
    <path d="M3,13H5V11H3V13M3,17H5V15H3V17M3,9H5V7H3V9M7,13H21V11H7V13M7,17H21V15H7V17M7,7V9H21V7H7Z" />
  </svg>
)

export default function SectorStrengthWidget() {
  const [data, setData] = useState<SectorStrengthData | null>(null)
  const [loading, setLoading] = useState(true)
  const [expandedIndustry, setExpandedIndustry] = useState<string | null>(null)
  const [stocksCache, setStocksCache] = useState<Map<string, SectorStockItem[]>>(new Map())
  const [loadingIndustry, setLoadingIndustry] = useState<string | null>(null)

  useEffect(() => {
    api.get('/market/sector-strength')
      .then(r => {
        setData(r.data)
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [])

  const handleIndustryClick = useCallback(async (industry: string) => {
    if (expandedIndustry === industry) {
      setExpandedIndustry(null)
      return
    }
    setExpandedIndustry(industry)
    if (stocksCache.has(industry)) return
    setLoadingIndustry(industry)
    try {
      const res = await api.get('/market/sector-stocks', { params: { industry, top: 10 } })
      setStocksCache(prev => new Map(prev).set(industry, res.data.stocks ?? []))
    } catch {
      setStocksCache(prev => new Map(prev).set(industry, []))
    } finally {
      setLoadingIndustry(null)
    }
  }, [expandedIndustry, stocksCache])

  const formatRs = (val: number) => (val >= 0 ? `+${val.toFixed(1)}` : val.toFixed(1))

  const renderStockList = (industry: string) => {
    const isLoading = loadingIndustry === industry
    const stocks = stocksCache.get(industry)
    if (isLoading) {
      return (
        <div className="mt-1 mb-2 pl-2 border-l border-zinc-700/60 space-y-1 py-1">
          {[0, 1, 2].map(i => (
            <div key={i} className="h-3 bg-zinc-700/40 rounded animate-pulse" />
          ))}
        </div>
      )
    }
    if (!stocks || stocks.length === 0) {
      return (
        <div className="mt-1 mb-2 pl-2 border-l border-zinc-700/60">
          <p className="text-[10px] text-zinc-500 py-1">無資料</p>
        </div>
      )
    }
    return (
      <div className="mt-1 mb-2 pl-2 border-l border-zinc-700/60 space-y-0.5 py-1">
        {stocks.map((s, idx) => (
          <div key={s.stock_id} className="flex items-center gap-1 text-[10px] font-mono">
            <span className="text-zinc-600 w-3 shrink-0">{idx + 1}</span>
            <span className="text-zinc-500 w-10 shrink-0">{s.stock_id}</span>
            <span className="text-zinc-300 flex-1 truncate">{s.name}</span>
            <span className={s.ret20 >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
              {s.ret20 >= 0 ? `+${s.ret20.toFixed(1)}` : s.ret20.toFixed(1)}%
            </span>
          </div>
        ))}
      </div>
    )
  }

  const renderIndustryList = (items: SectorItem[], side: 'top' | 'bottom') => (
    <div>
      <p className={`text-xs font-medium mb-2 ${side === 'top' ? 'text-emerald-400' : 'text-rose-400'}`}>
        {side === 'top' ? '近20日漲幅居前' : '近20日漲幅居後'}
      </p>
      <div className="space-y-0.5">
        {items.map((item) => {
          const isExpanded = expandedIndustry === item.industry
          return (
            <div key={item.industry}>
              <div
                className="flex items-center justify-between cursor-pointer hover:opacity-75 transition-opacity py-0.5"
                onClick={() => handleIndustryClick(item.industry)}
              >
                <span className={`text-xs text-zinc-300 truncate max-w-[100px] ${isExpanded ? 'underline decoration-dotted underline-offset-2' : ''}`}>
                  {item.industry}
                </span>
                <span className={`text-xs font-mono ml-1 ${side === 'top' ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {formatRs(item.median_rs)}
                </span>
              </div>
              {isExpanded && renderStockList(item.industry)}
            </div>
          )
        })}
      </div>
    </div>
  )

  if (loading) {
    return (
      <div className="bg-zinc-900/60 border border-white/10 rounded-2xl px-4 py-3">
        <div className="flex justify-between items-center mb-3 pb-2 border-b border-zinc-800/40">
          <span className="text-amber-400 text-sm font-bold flex items-center gap-1.5">
            <SectorIcon />
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
            <SectorIcon />
            產業輪動強弱
          </span>
        </div>
        <p className="text-xs text-zinc-500">產業資料尚未就緒，請先執行特徵回補</p>
      </div>
    )
  }

  return (
    <div className="bg-zinc-900/60 border border-white/10 rounded-2xl px-4 py-3">
      <div className="flex justify-between items-center mb-3 pb-2 border-b border-zinc-800/40">
        <span className="text-amber-400 text-sm font-bold flex items-center gap-1.5">
          <SectorIcon />
          產業輪動強弱
        </span>
        <span className="text-zinc-400 text-[10px] font-mono font-normal">{data.date}</span>
      </div>

      <div className="grid grid-cols-2 gap-3">
        {renderIndustryList(data.top, 'top')}
        {renderIndustryList(data.bottom, 'bottom')}
      </div>
    </div>
  )
}
