import React, { useState, useEffect } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/router'
import StockSearch from '../components/StockSearch'
import MarketRanking from '../components/MarketRanking'
import api from '../lib/api'
import Head from 'next/head'

export default function Home() {
  const router = useRouter()
  const [loading, setLoading] = useState(false)

  const handleSearch = async (symbol: string) => {
    const q = symbol.trim()
    if (!q) return

    if (/^\d{4,}$/.test(q)) {
      router.push(`/stock/${q}`)
      return
    }

    setLoading(true)
    try {
      const res = await api.get(`/stocks/search?q=${encodeURIComponent(q)}`)
      const data = res.data
      const results = data.results || []

      if (results.length > 0) {
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
    <>
      <Head>
        <title>AlphaForge_ | 專業級台股策略鍛造平台</title>
        <meta name="description" content="AlphaForge 為投資者提供最強大的台股策略研發與回測工具，助您鍛造出高勝率的投資組合。" />
        <link rel="icon" type="image/svg+xml" href="/alphaforge/favicon.svg" />
      </Head>

      <div className="min-h-screen bg-brand-dark text-gray-100 flex flex-col">
        {/* Header */}
        <header className="bg-brand-dark/80 backdrop-blur-lg sticky top-0 z-50 transition-all duration-300 border-b border-zinc-800/50">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex justify-between items-center">
            <Link href="/" className="text-2xl font-bold text-neutral-50 tracking-tight transition-all flex items-center gap-2">
              <svg viewBox="0 0 24 24" width="32" height="32" fill="#34d399" className="w-8 h-8 fill-emerald-400">
                <path d="M12,2A10,10 0 0,0 2,12A10,10 0 0,0 12,22A10,10 0 0,0 22,12A10,10 0 0,0 12,2M12,4A8,8 0 0,1 20,12A8,8 0 0,1 12,20A8,8 0 0,1 4,12A8,8 0 0,1 12,4M12,6A6,6 0 0,0 6,12A6,6 0 0,0 12,18A6,6 0 0,0 18,12A6,6 0 0,0 12,6M12,8A4,4 0 0,1 16,12A4,4 0 0,1 12,16A4,4 0 0,1 8,12A4,4 0 0,1 12,8M12,10A2,2 0 0,0 10,12A2,2 0 0,0 12,14A2,2 0 0,0 14,12A2,2 0 0,0 12,10Z" />
              </svg>
              <span>AlphaForge<span className="text-emerald-400">_</span></span>
            </Link>
            <nav className="flex gap-6">
              <Link href="/" className="text-neutral-50 font-semibold hover:text-cyan-400 transition-colors">
                首頁
              </Link>
              <Link href="/portfolio" className="text-neutral-400 hover:text-cyan-400 font-medium transition-colors">
                投資組合
              </Link>
            </nav>
          </div>
        </header>

        <section className="relative bg-brand-dark pt-1 sm:pt-10 pb-2 sm:pb-6 border-b border-zinc-900">
          <div className="relative z-10 max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col items-center">
            <div className="w-full">
              <StockSearch onSearch={handleSearch} />
            </div>
            {loading && (
              <div className="mt-8 flex justify-center items-center gap-3 text-neutral-500">
                <svg className="animate-spin h-6 w-6 text-emerald-400" width="24" height="24" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                <span className="text-base sm:text-lg font-mono animate-pulse tracking-widest text-emerald-400">正在獲取最新數據...</span>
              </div>
            )}
          </div>
        </section>

        <main className="flex-grow max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-2 sm:pt-8 pb-6 sm:pb-10 w-full">
          <section className="mb-10 sm:mb-16">
            <MarketRanking />
          </section>
        </main>

        {/* Footer */}
        <footer className="bg-brand-dark text-neutral-400 py-8 sm:py-12 border-t border-zinc-900 mt-auto">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="flex flex-col items-center justify-center">
              <div className="text-2xl font-bold text-neutral-50 tracking-tight flex items-center gap-2">
                <svg viewBox="0 0 24 24" width="32" height="32" fill="#34d399" className="w-8 h-8 fill-emerald-400">
                  <path d="M12,2A10,10 0 0,0 2,12A10,10 0 0,0 12,22A10,10 0 0,0 22,12A10,10 0 0,0 12,2M12,4A8,8 0 0,1 20,12A8,8 0 0,1 12,20A8,8 0 0,1 4,12A8,8 0 0,1 12,4M12,6A6,6 0 0,0 6,12A6,6 0 0,0 12,18A6,6 0 0,0 18,12A6,6 0 0,0 12,6M12,8A4,4 0 0,1 16,12A4,4 0 0,1 12,16A4,4 0 0,1 8,12A4,4 0 0,1 12,8M12,10A2,2 0 0,0 10,12A2,2 0 0,0 12,14A2,2 0 0,0 14,12A2,2 0 0,0 12,10Z" />
                </svg>
                AlphaForge<span className="text-emerald-400">_</span>
              </div>
              <div className="mt-8 pt-8 border-t border-zinc-900 w-full text-center">
                <p className="font-mono text-xs uppercase tracking-widest">
                  SYSTEM.COPYRIGHT &copy; {new Date().getFullYear()}
                </p>
              </div>
            </div>
          </div>
        </footer>
      </div>
    </>
  )
}
