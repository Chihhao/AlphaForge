import React, { useState, useEffect } from 'react'
import { useRouter } from 'next/router'
import Link from 'next/link'
import dynamic from 'next/dynamic'
import api from '../../lib/api'

const TVChart = dynamic(() => import('../../components/TVChart'), { ssr: false })

export default function StockDetail() {
  const router = useRouter()
  const { id } = router.query

  const [activeTab, setActiveTab] = useState<'1d' | '5d' | '1m' | '3m' | '1y'>('1d')
  const [quote, setQuote] = useState<any>(null)
  const [chartData, setChartData] = useState<Array<any>>([])
  const [indicators, setIndicators] = useState<any>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!id) return
    const fetchData = async () => {
      setLoading(true)
      try {
        // Map frontend tab values to yfinance period values
        const periodMap: Record<string, string> = {
          '1d': '1d',
          '5d': '5d',
          '1m': '1mo',
          '3m': '3mo',
          '1y': '1y'
        }

        const apiPeriod = periodMap[activeTab] || '1mo'
        const apiInterval = activeTab === '1d' ? '5m' : '1d' // For 1 day period, use 5min interval for better line chart

        // Fetch quote data for the current id
        const qres = await api.get(`/stocks/${id}/quote`)
        setQuote(qres.data)

        const kres = await api.get(`/stocks/${id}/kline?period=${apiPeriod}&interval=${apiInterval}`)
        const kd = kres.data
        const data = (kd.data || []).map((r: any) => {
          const ts = Math.floor(new Date(r.date).getTime() / 1000);
          const isUp = r.close >= r.open;
          return {
            time: ts,
            open: r.open,
            high: r.high,
            low: r.low,
            close: r.close,
            volume: r.volume,
            isUp
          };
        })

        // Ensure no duplicate timestamps and sorted
        const uniqueData = data.filter((v: any, i: number, a: any[]) => a.findIndex(t => (t.time === v.time)) === i)
        uniqueData.sort((a: any, b: any) => a.time - b.time)

        setChartData(uniqueData)

        const ires = await api.get(`/stocks/${id}/indicators?period=${apiPeriod}&interval=${apiInterval}`)
        const indData = ires.data
        if (indData.data && indData.data.length > 0) {
          // Get the most recent valid indicators
          setIndicators(indData.data[indData.data.length - 1])
        }
      } catch (e) {
        console.error('fetch stock data error', e)
      } finally {
        setLoading(false)
      }
    }
    fetchData()
  }, [id, activeTab])

  if (!id) return <div className="text-center py-8">載入中...</div>

  const displayName = quote?.stock_name || `股票 ${id}`
  const displayPrice = quote?.current_price ?? 0
  const displayChange = quote?.change_percent ?? 0

  return (
    <div className="flex-grow">
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 sm:py-6">
        {/* Stock Header */}
        <div className="bg-gray-800 rounded-lg shadow-lg border border-gray-700 p-6 mb-4 sm:mb-6">
          <div className="flex justify-between items-start mb-4">
            <div>
              <h1 className="text-3xl font-bold text-gray-100">{displayName}</h1>
              <p className="text-gray-400">股票代號：{id}</p>
            </div>
            <div className="text-right">
              <p className="text-4xl font-bold text-gray-100">NT${displayPrice.toFixed(2)}</p>
              <p className={`text-xl font-semibold ${displayChange >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                {displayChange >= 0 ? '+' : ''}{displayChange.toFixed(2)}%
              </p>
            </div>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-5 gap-4 pt-4 border-t border-gray-700">
            <div>
              <p className="text-sm text-gray-400">開盤</p>
              <p className="text-lg font-semibold">NT${quote?.open_price?.toFixed(2) ?? '---'}</p>
            </div>
            <div>
              <p className="text-sm text-gray-400">最高</p>
              <p className="text-lg font-semibold">NT${quote?.high_price?.toFixed(2) ?? '---'}</p>
            </div>
            <div>
              <p className="text-sm text-gray-400">最低</p>
              <p className="text-lg font-semibold">NT${quote?.low_price?.toFixed(2) ?? '---'}</p>
            </div>
            <div>
              <p className="text-sm text-gray-400">成交量</p>
              <p className="text-lg font-semibold">
                {quote?.volume
                  ? quote.volume >= 1000000
                    ? (quote.volume / 1000000).toFixed(1) + 'M'
                    : quote.volume >= 1000
                      ? (quote.volume / 1000).toFixed(1) + 'K'
                      : quote.volume
                  : '---'}
              </p>
            </div>
            <div>
              <p className="text-sm text-gray-400">庫存/市值</p>
              <p className="text-lg font-semibold">---</p>
            </div>
          </div>
        </div>

        {/* Chart Section */}
        <div className="bg-gray-800 rounded-lg shadow-lg border border-gray-700 p-6 mb-4 sm:mb-6">
          <div className="mb-4">
            <h2 className="text-xl font-bold text-gray-100 mb-4">K線圖表</h2>
            <div className="flex gap-2 mb-6">
              {(['1d', '5d', '1m', '3m', '1y'] as const).map(period => (
                <button
                  key={period}
                  onClick={() => setActiveTab(period)}
                  className={`px-4 py-2 rounded font-semibold transition ${activeTab === period
                    ? 'bg-gold-600 text-gray-900'
                    : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                    }`}
                >
                  {period === '1d' ? '日'
                    : period === '5d' ? '週'
                      : period === '1m' ? '月'
                        : period === '3m' ? '3月'
                          : '1年'}
                </button>
              ))}
            </div>
          </div>

          {/* Chart */}
          <div className="h-[400px] w-full border border-gray-700 rounded overflow-hidden">
            {chartData.length > 0 ? (
              <TVChart data={chartData} />
            ) : (
              <div className="flex items-center justify-center h-[400px] text-gray-500 bg-gray-900">
                載入圖台中...
              </div>
            )}
          </div>
        </div>

        {/* Technical Indicators */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 sm:gap-6 mb-4 sm:mb-6">
          <div className="bg-gray-800 rounded-lg shadow-lg border border-gray-700 p-6">
            <h2 className="text-xl font-bold text-gray-100 mb-4">主圖指標</h2>
            <div className="space-y-3">
              <div className="flex justify-between">
                <span className="text-gray-400">現價</span>
                <span className="font-semibold">NT${displayPrice.toFixed(2)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">MA20</span>
                <span className="font-semibold">{indicators?.ma20 ? `NT$${indicators.ma20.toFixed(2)}` : '---'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">MA50</span>
                <span className="font-semibold">{indicators?.ma50 ? `NT$${indicators.ma50.toFixed(2)}` : '---'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">布林通道上</span>
                <span className="font-semibold">{indicators?.bb_upper ? `NT$${indicators.bb_upper.toFixed(2)}` : '---'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">布林通道下</span>
                <span className="font-semibold">{indicators?.bb_lower ? `NT$${indicators.bb_lower.toFixed(2)}` : '---'}</span>
              </div>
            </div>
          </div>

          <div className="bg-gray-800 rounded-lg shadow-lg border border-gray-700 p-6">
            <h2 className="text-xl font-bold text-gray-100 mb-4">副圖指標</h2>
            <div className="space-y-3">
              <div className="flex justify-between">
                <span className="text-gray-400">RSI</span>
                <span className="font-semibold text-orange-500">{indicators?.rsi ? indicators.rsi.toFixed(2) : '---'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">MACD</span>
                <span className="font-semibold text-gray-500">尚未實作</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">KD 快慢線</span>
                <span className="font-semibold text-gray-500">尚未實作</span>
              </div>
            </div>
          </div>
        </div>

      </main>
    </div>
  )
}
