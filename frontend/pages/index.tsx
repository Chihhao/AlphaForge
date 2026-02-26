import React, { useState } from 'react'
import Link from 'next/link'
import StockSearch from '../components/StockSearch'
import StockCard from '../components/StockCard'

export default function Home() {
  const [stocks, setStocks] = useState<Array<{id:string;name:string;price:number;change:number}>>([])
  const [loading, setLoading] = useState(false)

  const handleSearch = async (symbol: string) => {
    setLoading(true)
    try {
      const res = await fetch(`http://localhost:8001/api/stocks/search?q=${encodeURIComponent(symbol)}`)
      const data = await res.json()
      const results = data.results || []

      // For each result, fetch quote to show price/change
      const enriched = await Promise.all(results.slice(0, 6).map(async (s: any) => {
        try {
          const q = await fetch(`http://localhost:8001/api/stocks/${s.stock_id}/quote`)
          const qd = await q.json()
          return {
            id: s.stock_id,
            name: s.stock_name,
            price: qd.current_price || 0,
            change: qd.change_percent || 0,
          }
        } catch (e) {
          return { id: s.stock_id, name: s.stock_name, price: 0, change: 0 }
        }
      }))

      setStocks(enriched)
    } catch (e) {
      console.error('搜尋錯誤', e)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100">
      {/* Header */}
      <header className="bg-white shadow-md sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex justify-between items-center">
          <h1 className="text-2xl font-bold text-indigo-600">TW Stock 168</h1>
          <nav className="flex gap-4">
            <Link href="/" className="text-gray-600 hover:text-indigo-600 font-medium">
              首頁
            </Link>
            <Link href="/trading" className="text-gray-600 hover:text-indigo-600 font-medium">
              模擬交易
            </Link>
            <Link href="/portfolio" className="text-gray-600 hover:text-indigo-600 font-medium">
              投資組合
            </Link>
          </nav>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Search Section */}
        <div className="mb-8">
          <StockSearch onSearch={handleSearch} />
        </div>

        {/* Featured Stocks */}
        <section className="mb-12">
          <h2 className="text-2xl font-bold text-gray-800 mb-6">熱門股票</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {stocks.length === 0 && (
              <p className="text-gray-500">尚無搜尋結果，請使用上方搜尋框查詢真實資料。</p>
            )}
            {stocks.map(stock => (
              <Link key={stock.id} href={`/stock/${stock.id}`}>
                <StockCard stock={stock} />
              </Link>
            ))}
          </div>
        </section>

        {/* Quick Actions */}
        <section className="bg-white rounded-lg shadow-lg p-8">
          <h2 className="text-2xl font-bold text-gray-800 mb-6">快速開始</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="bg-indigo-50 p-6 rounded-lg border border-indigo-200">
              <h3 className="text-lg font-semibold text-indigo-600 mb-2">📊 查看行情</h3>
              <p className="text-gray-600 mb-4">即時查詢台灣上市櫃股票的K線圖表和技術指標</p>
              <button className="bg-indigo-600 text-white px-4 py-2 rounded hover:bg-indigo-700 transition">
                開始查詢
              </button>
            </div>
            <div className="bg-green-50 p-6 rounded-lg border border-green-200">
              <h3 className="text-lg font-semibold text-green-600 mb-2">💰 模擬交易</h3>
              <p className="text-gray-600 mb-4">使用虛擬資金驗證交易策略，無需承擔真實風險</p>
              <Link href="/trading">
                <button className="bg-green-600 text-white px-4 py-2 rounded hover:bg-green-700 transition">
                  開始交易
                </button>
              </Link>
            </div>
            <div className="bg-purple-50 p-6 rounded-lg border border-purple-200">
              <h3 className="text-lg font-semibold text-purple-600 mb-2">📈 績效分析</h3>
              <p className="text-gray-600 mb-4">追蹤投資組合表現，分析報酬率和風險指標</p>
              <Link href="/portfolio">
                <button className="bg-purple-600 text-white px-4 py-2 rounded hover:bg-purple-700 transition">
                  查看組合
                </button>
              </Link>
            </div>
          </div>
        </section>
      </main>

      {/* Footer */}
      <footer className="bg-gray-800 text-white mt-16 py-8">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <p className="text-center text-gray-400">
            © 2026 Taiwan Stock 168. 本平台僅用於教育與模擬交易用途，非投資建議。
          </p>
        </div>
      </footer>
    </div>
  )
}
