import React, { useState } from 'react'
import Link from 'next/link'
import { formatPrice } from '../lib/formatters'

interface Order {
  id: string
  symbol: string
  name: string
  type: 'buy' | 'sell'
  shares: number
  price: number
  date: string
  status: 'pending' | 'filled'
}

const mockOrders: Order[] = [
  { id: '1', symbol: '2330', name: '台積電', type: 'buy',  shares: 10, price: 2010, date: '2026-02-24 10:30', status: 'filled' },
  { id: '2', symbol: '2454', name: '聯發科', type: 'buy',  shares: 5,  price: 850,  date: '2026-02-25 09:15', status: 'filled' },
]

export default function Trading() {
  const [activeTab, setActiveTab] = useState<'portfolio' | 'orders'>('portfolio')

  return (
    <div className="flex-grow">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <h1 className="text-3xl font-bold text-gray-100 mb-8 border-l-4 border-amber-400 pl-4">模擬交易</h1>

        {/* Account Summary */}
        <div className="bg-zinc-900/40 rounded-xl border border-zinc-800/50 p-6 mb-8">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
            <div>
              <p className="text-zinc-500 text-xs uppercase tracking-widest mb-1">帳戶餘額</p>
              <p className="text-2xl font-bold text-zinc-100 font-mono">850,000</p>
            </div>
            <div>
              <p className="text-zinc-500 text-xs uppercase tracking-widest mb-1">持股市值</p>
              <p className="text-2xl font-bold text-zinc-100 font-mono">150,000</p>
            </div>
            <div>
              <p className="text-zinc-500 text-xs uppercase tracking-widest mb-1">總資產</p>
              <p className="text-2xl font-bold text-zinc-100 font-mono">1,000,000</p>
            </div>
            <div>
              <p className="text-zinc-500 text-xs uppercase tracking-widest mb-1">損益</p>
              <p className="text-2xl font-bold text-rose-400 font-mono">+5,000</p>
            </div>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex gap-2 mb-6">
          {(['portfolio', 'orders'] as const).map(tab => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-2 rounded-xl text-sm font-semibold transition-all border cursor-pointer ${
                activeTab === tab
                  ? 'bg-amber-500/10 border-amber-500/50 text-amber-400'
                  : 'bg-zinc-900/40 border-zinc-800 text-zinc-500 hover:text-zinc-200 hover:border-zinc-600'
              }`}
            >
              {tab === 'portfolio' ? '持股組合' : '訂單紀錄'}
            </button>
          ))}
        </div>

        {/* Portfolio Tab */}
        {activeTab === 'portfolio' && (
          <div className="bg-zinc-900/40 rounded-xl border border-zinc-800/50 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b border-zinc-800">
                  <tr>
                    {['股票', '代號', '持股', '均價', '現價', '市值', '損益', '操作'].map(h => (
                      <th key={h} className={`px-5 py-3 ${h === '股票' || h === '代號' || h === '操作' ? 'text-left' : 'text-right'} font-medium text-zinc-500 whitespace-nowrap`}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  <tr className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
                    <td className="px-5 py-4 text-zinc-200 font-medium">台積電</td>
                    <td className="px-5 py-4 text-zinc-500 font-mono text-xs">2330</td>
                    <td className="px-5 py-4 text-right font-semibold text-zinc-300">10</td>
                    <td className="px-5 py-4 text-right font-mono text-zinc-400">2,010</td>
                    <td className="px-5 py-4 text-right font-mono text-zinc-200">2,015</td>
                    <td className="px-5 py-4 text-right font-mono font-semibold text-zinc-200">20,150</td>
                    <td className="px-5 py-4 text-right font-mono font-semibold text-rose-400">+50</td>
                    <td className="px-5 py-4">
                      <Link href="/stock/2330" className="text-amber-400 hover:text-amber-300 text-xs transition-colors">
                        查看 →
                      </Link>
                    </td>
                  </tr>
                  <tr className="hover:bg-zinc-800/30">
                    <td className="px-5 py-4 text-zinc-200 font-medium">聯發科</td>
                    <td className="px-5 py-4 text-zinc-500 font-mono text-xs">2454</td>
                    <td className="px-5 py-4 text-right font-semibold text-zinc-300">5</td>
                    <td className="px-5 py-4 text-right font-mono text-zinc-400">850</td>
                    <td className="px-5 py-4 text-right font-mono text-zinc-200">890</td>
                    <td className="px-5 py-4 text-right font-mono font-semibold text-zinc-200">4,450</td>
                    <td className="px-5 py-4 text-right font-mono font-semibold text-rose-400">+200</td>
                    <td className="px-5 py-4">
                      <Link href="/stock/2454" className="text-amber-400 hover:text-amber-300 text-xs transition-colors">
                        查看 →
                      </Link>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div className="px-5 py-3 border-t border-zinc-800 text-zinc-600 text-xs">
              共 2 筆持股 · 示例資料僅供展示
            </div>
          </div>
        )}

        {/* Orders Tab */}
        {activeTab === 'orders' && (
          <div className="bg-zinc-900/40 rounded-xl border border-zinc-800/50 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b border-zinc-800">
                  <tr>
                    {['股票', '類型', '股數', '價格', '時間', '狀態'].map(h => (
                      <th key={h} className={`px-5 py-3 ${h === '股票' || h === '時間' || h === '狀態' || h === '類型' ? 'text-left' : 'text-right'} font-medium text-zinc-500 whitespace-nowrap`}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {mockOrders.map(order => (
                    <tr key={order.id} className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
                      <td className="px-5 py-4">
                        <span className="text-zinc-200 font-medium">{order.name}</span>
                        <span className="text-zinc-600 font-mono text-xs ml-1.5">{order.symbol}</span>
                      </td>
                      <td className="px-5 py-4">
                        <span className={`px-2 py-0.5 rounded-full text-xs font-semibold border ${
                          order.type === 'buy'
                            ? 'bg-rose-500/10 text-rose-400 border-rose-500/25'
                            : 'bg-emerald-500/10 text-emerald-400 border-emerald-500/25'
                        }`}>
                          {order.type === 'buy' ? '買進' : '賣出'}
                        </span>
                      </td>
                      <td className="px-5 py-4 text-right text-zinc-300">{order.shares}</td>
                      <td className="px-5 py-4 text-right font-mono text-zinc-300">{formatPrice(order.price)}</td>
                      <td className="px-5 py-4 text-zinc-500 text-xs font-mono">{order.date}</td>
                      <td className="px-5 py-4">
                        <span className={`px-2 py-0.5 rounded-full text-xs font-semibold border ${
                          order.status === 'filled'
                            ? 'bg-zinc-700/50 text-zinc-400 border-zinc-600'
                            : 'bg-amber-500/10 text-amber-400 border-amber-500/25'
                        }`}>
                          {order.status === 'filled' ? '已成交' : '待成交'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="px-5 py-3 border-t border-zinc-800 text-zinc-600 text-xs">
              共 {mockOrders.length} 筆訂單 · 示例資料僅供展示
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
