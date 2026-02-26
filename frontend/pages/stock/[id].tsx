import React, { useState, useEffect } from 'react'
import { useRouter } from 'next/router'
import Link from 'next/link'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'

export default function StockDetail() {
  const router = useRouter()
  const { id } = router.query

  const [activeTab, setActiveTab] = useState<'1d' | '5d' | '1m' | '3m' | '1y'>('1d')
  const [quote, setQuote] = useState<any>(null)
  const [chartData, setChartData] = useState<Array<any>>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!id) return
    const fetchData = async () => {
      setLoading(true)
      try {
        const qres = await fetch(`http://localhost:8001/api/stocks/${id}/quote`)
        if (qres.ok) setQuote(await qres.json())

        const kres = await fetch(`http://localhost:8001/api/stocks/${id}/kline?period=1mo&interval=1d`)
        if (kres.ok) {
          const kd = await kres.json()
          const data = (kd.data || []).map((r: any) => ({ date: r.date.slice(0,10), price: r.close }))
          setChartData(data)
        }
      } catch (e) {
        console.error('fetch stock data error', e)
      } finally {
        setLoading(false)
      }
    }
    fetchData()
  }, [id])

  if (!id) return <div className="text-center py-8">載入中...</div>

  const displayName = quote?.stock_name || `股票 ${id}`
  const displayPrice = quote?.current_price ?? 0
  const displayChange = quote?.change_percent ?? 0

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white shadow-md sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <Link href="/" className="text-indigo-600 hover:text-indigo-700">
            ← 返回首頁
          </Link>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Stock Header */}
        <div className="bg-white rounded-lg shadow-lg p-6 mb-6">
          <div className="flex justify-between items-start mb-4">
            <div>
              <h1 className="text-3xl font-bold text-gray-800">{displayName}</h1>
              <p className="text-gray-600">股票代號：{id}</p>
            </div>
            <div className="text-right">
              <p className="text-4xl font-bold text-gray-800">NT${displayPrice.toFixed(2)}</p>
              <p className={`text-xl font-semibold ${displayChange >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                {displayChange >= 0 ? '+' : ''}{displayChange.toFixed(2)}%
              </p>
            </div>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-5 gap-4 pt-4 border-t">
            <div>
              <p className="text-sm text-gray-500">開盤</p>
              <p className="text-lg font-semibold">NT$2010.00</p>
            </div>
            <div>
              <p className="text-sm text-gray-500">最高</p>
              <p className="text-lg font-semibold">NT$2020.00</p>
            </div>
            <div>
              <p className="text-sm text-gray-500">最低</p>
              <p className="text-lg font-semibold">NT$2000.00</p>
            </div>
            <div>
              <p className="text-sm text-gray-500">成交量</p>
              <p className="text-lg font-semibold">15.2M</p>
            </div>
            <div>
              <p className="text-sm text-gray-500">市值</p>
              <p className="text-lg font-semibold">18.3T</p>
            </div>
          </div>
        </div>

        {/* Chart Section */}
        <div className="bg-white rounded-lg shadow-lg p-6 mb-6">
          <div className="mb-4">
            <h2 className="text-xl font-bold text-gray-800 mb-4">K線圖表</h2>
            <div className="flex gap-2 mb-6">
              {(['1d', '5d', '1m', '3m', '1y'] as const).map(period => (
                <button
                  key={period}
                  onClick={() => setActiveTab(period)}
                  className={`px-4 py-2 rounded font-semibold transition ${
                    activeTab === period
                      ? 'bg-indigo-600 text-white'
                      : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
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
          <ResponsiveContainer width="100%" height={400}>
            <LineChart data={chartData.length>0?chartData:[{date:'',price:0}] }>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="date" />
              <YAxis domain={['dataMin - 5', 'dataMax + 5']} />
              <Tooltip formatter={(value) => `NT$${value}`} />
              <Line
                type="monotone"
                dataKey="price"
                stroke="#4f46e5"
                dot={{ fill: '#4f46e5' }}
                strokeWidth={2}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* Technical Indicators */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
          <div className="bg-white rounded-lg shadow-lg p-6">
            <h2 className="text-xl font-bold text-gray-800 mb-4">主圖指標</h2>
            <div className="space-y-3">
              <div className="flex justify-between">
                <span className="text-gray-600">MA5</span>
                <span className="font-semibold">NT$2012.50</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">MA20</span>
                <span className="font-semibold">NT$2008.20</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">布林通道上</span>
                <span className="font-semibold">NT$2025.30</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">布林通道下</span>
                <span className="font-semibold">NT$1995.10</span>
              </div>
            </div>
          </div>

          <div className="bg-white rounded-lg shadow-lg p-6">
            <h2 className="text-xl font-bold text-gray-800 mb-4">副圖指標</h2>
            <div className="space-y-3">
              <div className="flex justify-between">
                <span className="text-gray-600">RSI</span>
                <span className="font-semibold text-orange-600">65.2</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">MACD</span>
                <span className="font-semibold text-green-600">正向</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">KD 快線</span>
                <span className="font-semibold">72.5</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">KD 慢線</span>
                <span className="font-semibold">68.3</span>
              </div>
            </div>
          </div>
        </div>

        {/* Trading Section */}
        <div className="bg-white rounded-lg shadow-lg p-6">
          <h2 className="text-xl font-bold text-gray-800 mb-4">下單</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Buy Order */}
            <div className="border-l-4 border-green-600 pl-4">
              <h3 className="text-lg font-semibold text-green-600 mb-4">買入</h3>
              <div className="space-y-3">
                <div>
                  <label className="block text-sm text-gray-600 mb-1">數量 (股)</label>
                  <input
                    type="number"
                    placeholder="輸入股數"
                    className="w-full px-3 py-2 border border-gray-300 rounded"
                  />
                </div>
                <div>
                  <label className="block text-sm text-gray-600 mb-1">訂單類型</label>
                  <select className="w-full px-3 py-2 border border-gray-300 rounded">
                    <option>市價單</option>
                    <option>限價單</option>
                  </select>
                </div>
                <button className="w-full bg-green-600 text-white py-2 rounded hover:bg-green-700 transition font-semibold">
                  確認買入
                </button>
              </div>
            </div>

            {/* Sell Order */}
            <div className="border-l-4 border-red-600 pl-4">
              <h3 className="text-lg font-semibold text-red-600 mb-4">賣出</h3>
              <div className="space-y-3">
                <div>
                  <label className="block text-sm text-gray-600 mb-1">數量 (股)</label>
                  <input
                    type="number"
                    placeholder="輸入股數"
                    className="w-full px-3 py-2 border border-gray-300 rounded"
                  />
                </div>
                <div>
                  <label className="block text-sm text-gray-600 mb-1">訂單類型</label>
                  <select className="w-full px-3 py-2 border border-gray-300 rounded">
                    <option>市價單</option>
                    <option>限價單</option>
                  </select>
                </div>
                <button className="w-full bg-red-600 text-white py-2 rounded hover:bg-red-700 transition font-semibold">
                  確認賣出
                </button>
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}
