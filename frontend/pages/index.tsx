import React, { useState, useEffect } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/router'
import StockSearch from '../components/StockSearch'
import StockCard from '../components/StockCard'
import api from '../lib/api'

export default function Home() {
  const router = useRouter()
  const [stocks, setStocks] = useState<Array<{ id: string; name: string; price: number; change: number }>>([])
  const [loading, setLoading] = useState(false)

  // 預設載入熱門股票
  useEffect(() => {
    const fetchDefaults = async () => {
      setLoading(true)
      const defaultIds = ['2330', '2317', '2454', '2881', '2603', '2882']
      try {
        const enriched = await Promise.all(defaultIds.map(async (id) => {
          try {
            const q = await api.get(`/api/stocks/${id}/quote`)
            const qd = q.data
            return {
              id: id,
              name: qd.stock_name || id,
              price: qd.current_price || 0,
              change: qd.change_percent || 0,
            }
          } catch (e) {
            return { id, name: id, price: 0, change: 0 }
          }
        }))
        setStocks(enriched)
      } catch (e) {
        console.error('Initial fetch error', e)
      } finally {
        setLoading(false)
      }
    }
    fetchDefaults()
  }, [])

  const handleSearch = async (symbol: string) => {
    const q = symbol.trim()
    if (!q) return

    // 如果輸入的是純數字代號（至少4碼），直接跳轉以節省 API 請求
    if (/^\d{4,}$/.test(q)) {
      router.push(`/stock/${q}`)
      return
    }

    setLoading(true)
    try {
      const res = await api.get(`/api/stocks/search?q=${encodeURIComponent(q)}`)
      const data = res.data
      const results = data.results || []

      if (results.length > 0) {
        // 直接取第一筆搜尋結果的代號進行跳轉
        router.push(`/stock/${results[0].stock_id}`)
      } else {
        alert(`找不到與「${q}」相關的股票，請確認後再試。`)
      }
    } catch (e) {
      console.error('搜尋錯誤', e)
      alert('搜尋發生錯誤，請稍後再試。')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-900 text-gray-100 flex flex-col">
      {/* Header */}
      <header className="bg-gray-900/80 backdrop-blur-md shadow-md border-b border-gray-800 sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex justify-between items-center">
          <Link href="/" className="text-2xl font-bold text-gold-500 tracking-tight hover:text-gold-400 transition-colors">
            AlphaForge
          </Link>
          <nav className="flex gap-6">
            <Link href="/" className="text-gray-100 font-semibold hover:text-gold-400 transition-colors">
              首頁
            </Link>
            <Link href="/trading" className="text-gray-400 hover:text-gold-400 font-medium transition-colors">
              模擬交易
            </Link>
            <Link href="/portfolio" className="text-gray-400 hover:text-gold-400 font-medium transition-colors">
              投資組合
            </Link>
          </nav>
        </div>
      </header>

      {/* Hero Section */}
      <section className="relative bg-gradient-to-br from-gray-900 via-gray-800 to-black text-gray-100 py-24 sm:py-32 overflow-hidden shadow-xl border-b border-gray-800">
        {/* Decorative background shapes */}
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <div className="absolute -top-40 -left-40 w-96 h-96 bg-gold-900 rounded-full mix-blend-screen filter blur-3xl opacity-20 animate-pulse"></div>
          <div className="absolute top-20 -right-20 w-[30rem] h-[30rem] bg-yellow-900 rounded-full mix-blend-screen filter blur-3xl opacity-20 animate-pulse" style={{ animationDelay: '2s' }}></div>
          <div className="absolute -bottom-40 left-1/2 w-96 h-96 bg-gold-800 rounded-full mix-blend-screen filter blur-3xl opacity-20 animate-pulse" style={{ animationDelay: '4s' }}></div>
        </div>

        <div className="relative z-10 max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
          <h1 className="text-4xl sm:text-5xl lg:text-7xl font-extrabold tracking-tight mb-8">
            掌握台股先機，<span className="text-transparent bg-clip-text bg-gradient-to-r from-gold-400 to-yellow-200">精準投資</span>
          </h1>
          <p className="text-lg sm:text-2xl text-gray-300 mb-12 max-w-3xl mx-auto font-light leading-relaxed">
            即時報價、專業 K 線圖、技術指標分析及真實模擬交易，您的全方位台股投資利器。
          </p>
          <div className="w-full">
            <StockSearch onSearch={handleSearch} />
          </div>
          {loading && (
            <div className="mt-8 flex justify-center items-center gap-3 text-gray-400">
              <svg className="animate-spin h-6 w-6 text-gold-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              <span className="text-lg animate-pulse">正在為您讀取最新精選數據...</span>
            </div>
          )}
        </div>
      </section>

      {/* Main Content */}
      <main className="flex-grow max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-16 w-full">
        {/* Featured Stocks */}
        <section className="mb-20">
          <div className="flex flex-col sm:flex-row justify-between items-baseline mb-10 gap-4">
            <h2 className="text-3xl sm:text-4xl font-bold text-gray-100 border-l-4 border-gold-500 pl-4 tracking-tight">市場焦點</h2>
            <p className="text-gray-400 sm:text-lg font-medium">即時熱度推薦，點擊卡片查看詳細分析</p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-8">
            {stocks.length === 0 && !loading && (
              <div className="col-span-full text-center py-20 bg-gray-800 rounded-3xl shadow-sm border-2 border-dashed border-gray-700">
                <p className="text-gray-400 text-xl font-medium">尚無資料，請使用上方搜尋框查詢。</p>
              </div>
            )}
            {stocks.map(stock => (
              <div key={stock.id} className="transform transition-all duration-300 hover:-translate-y-2 hover:shadow-2xl h-full">
                <Link href={`/stock/${stock.id}`} className="block h-full">
                  <StockCard stock={stock} />
                </Link>
              </div>
            ))}
          </div>
        </section>

        {/* Quick Actions */}
        {/* 快速功能導覽：暫時移除
        <section className="mb-12">
          <h2 className="text-3xl sm:text-4xl font-bold text-gray-800 mb-10 border-l-4 border-indigo-600 pl-4 tracking-tight">快速功能導覽</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            <div className="group relative bg-white rounded-3xl shadow-lg hover:shadow-2xl border border-gray-100 overflow-hidden transform transition-all duration-300 hover:-translate-y-3 cursor-pointer">
              <div className="absolute top-0 right-0 w-40 h-40 bg-indigo-50 rounded-bl-full -z-10 group-hover:scale-150 transition-transform duration-700 ease-out"></div>
              <div className="p-10 h-full flex flex-col">
                <div className="w-16 h-16 bg-indigo-100 text-indigo-600 rounded-2xl flex items-center justify-center text-3xl mb-8 shadow-inner ring-1 ring-white/50">📊</div>
                <h3 className="text-2xl font-bold text-gray-800 mb-4 group-hover:text-indigo-600 transition-colors">查看行情</h3>
                <p className="text-gray-600 mb-8 leading-relaxed flex-grow text-lg">即時查詢台灣上市櫃股票的專業級 K 線圖表與豐富技術指標，掌握最新走勢。</p>
                <button className="self-start text-indigo-600 font-semibold group-hover:text-white group-hover:bg-indigo-600 px-6 py-3 rounded-xl transition-all duration-300 border border-indigo-200 group-hover:border-indigo-600 text-lg shadow-sm">
                  開啟圖表 &rarr;
                </button>
              </div>
            </div>

            <Link href="/trading" className="block h-full">
              <div className="group relative bg-white rounded-3xl shadow-lg hover:shadow-2xl border border-gray-100 overflow-hidden transform transition-all duration-300 hover:-translate-y-3 h-full">
                <div className="absolute top-0 right-0 w-40 h-40 bg-emerald-50 rounded-bl-full -z-10 group-hover:scale-150 transition-transform duration-700 ease-out"></div>
                <div className="p-10 h-full flex flex-col">
                  <div className="w-16 h-16 bg-emerald-100 text-emerald-600 rounded-2xl flex items-center justify-center text-3xl mb-8 shadow-inner ring-1 ring-white/50">💰</div>
                  <h3 className="text-2xl font-bold text-gray-800 mb-4 group-hover:text-emerald-600 transition-colors">模擬交易</h3>
                  <p className="text-gray-600 mb-8 leading-relaxed flex-grow text-lg">使用千萬虛擬資金驗證您的獨家交易策略，體驗市場起伏而無需承擔真實風險。</p>
                  <button className="self-start text-emerald-600 font-semibold group-hover:text-white group-hover:bg-emerald-600 px-6 py-3 rounded-xl transition-all duration-300 border border-emerald-200 group-hover:border-emerald-600 text-lg shadow-sm">
                    開始練功 &rarr;
                  </button>
                </div>
              </div>
            </Link>

            <Link href="/portfolio" className="block h-full">
              <div className="group relative bg-white rounded-3xl shadow-lg hover:shadow-2xl border border-gray-100 overflow-hidden transform transition-all duration-300 hover:-translate-y-3 h-full">
                <div className="absolute top-0 right-0 w-40 h-40 bg-purple-50 rounded-bl-full -z-10 group-hover:scale-150 transition-transform duration-700 ease-out"></div>
                <div className="p-10 h-full flex flex-col">
                  <div className="w-16 h-16 bg-purple-100 text-purple-600 rounded-2xl flex items-center justify-center text-3xl mb-8 shadow-inner ring-1 ring-white/50">📈</div>
                  <h3 className="text-2xl font-bold text-gray-800 mb-4 group-hover:text-purple-600 transition-colors">績效分析</h3>
                  <p className="text-gray-600 mb-8 leading-relaxed flex-grow text-lg">全方位追蹤您的投資組合表現，深度分析歷史報酬率與風險指標，優化決策。</p>
                  <button className="self-start text-purple-600 font-semibold group-hover:text-white group-hover:bg-purple-600 px-6 py-3 rounded-xl transition-all duration-300 border border-purple-200 group-hover:border-purple-600 text-lg shadow-sm">
                    查看戰績 &rarr;
                  </button>
                </div>
              </div>
            </Link>
          </div>
        </section>
        */}
      </main>

      {/* Footer */}
      <footer className="bg-black text-gray-300 py-12 border-t border-gray-800">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center">
            <h2 className="text-2xl font-bold text-gray-300 mb-4 tracking-tight">AlphaForge</h2>
            <p className="text-gray-400 text-base max-w-2xl mx-auto leading-relaxed">
              本平台僅用於軟體工程展示、教育與模擬交易用途，絕非任何形式之投資建議。投資有風險，任何交易前應謹慎評估。
            </p>
            <div className="mt-8 pt-8 border-t border-gray-800">
              <p className="text-gray-500 text-sm">
                © {new Date().getFullYear()} Taiwan Stock 168. All rights reserved.
              </p>
            </div>
          </div>
        </div>
      </footer>
    </div>
  )
}
