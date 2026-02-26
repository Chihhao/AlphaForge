import React, { useState } from 'react'
import Link from 'next/link'

interface Order {
  id: string
  symbol: string
  type: 'buy' | 'sell'
  shares: number
  price: number
  date: string
  status: 'pending' | 'filled'
}

const mockOrders: Order[] = [
  {
    id: '1',
    symbol: '2330',
    type: 'buy',
    shares: 10,
    price: 2010,
    date: '2026-02-24 10:30',
    status: 'filled',
  },
]

export default function Trading() {
  const [activeTab, setActiveTab] = useState<'portfolio' | 'orders'>('portfolio')

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white shadow-md sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex justify-between items-center">
          <div>
            <Link href="/" className="text-indigo-600 hover:text-indigo-700">
              ← 返回首頁
            </Link>
            <h1 className="text-2xl font-bold text-gray-800 mt-2">模擬交易</h1>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Account Summary */}
        <div className="bg-gradient-to-r from-indigo-600 to-purple-600 rounded-lg shadow-lg p-8 text-white mb-8">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
            <div>
              <p className="text-indigo-200 text-sm">帳戶餘額</p>
              <p className="text-3xl font-bold">NT$850,000</p>
            </div>
            <div>
              <p className="text-indigo-200 text-sm">持股市值</p>
              <p className="text-3xl font-bold">NT$150,000</p>
            </div>
            <div>
              <p className="text-indigo-200 text-sm">總資產</p>
              <p className="text-3xl font-bold">NT$1,000,000</p>
            </div>
            <div>
              <p className="text-indigo-200 text-sm">損益</p>
              <p className="text-3xl font-bold text-green-300">+NT$5,000</p>
            </div>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex gap-4 mb-6 border-b border-gray-200">
          <button
            onClick={() => setActiveTab('portfolio')}
            className={`px-4 py-2 font-semibold border-b-2 transition ${
              activeTab === 'portfolio'
                ? 'text-indigo-600 border-indigo-600'
                : 'text-gray-600 border-transparent hover:text-gray-800'
            }`}
          >
            持股組合
          </button>
          <button
            onClick={() => setActiveTab('orders')}
            className={`px-4 py-2 font-semibold border-b-2 transition ${
              activeTab === 'orders'
                ? 'text-indigo-600 border-indigo-600'
                : 'text-gray-600 border-transparent hover:text-gray-800'
            }`}
          >
            訂單紀錄
          </button>
        </div>

        {/* Portfolio Tab */}
        {activeTab === 'portfolio' && (
          <div className="bg-white rounded-lg shadow-lg overflow-hidden">
            <table className="w-full">
              <thead className="bg-gray-100 border-b">
                <tr>
                  <th className="px-6 py-3 text-left text-sm font-semibold text-gray-700">股票</th>
                  <th className="px-6 py-3 text-left text-sm font-semibold text-gray-700">代號</th>
                  <th className="px-6 py-3 text-right text-sm font-semibold text-gray-700">持股</th>
                  <th className="px-6 py-3 text-right text-sm font-semibold text-gray-700">均價</th>
                  <th className="px-6 py-3 text-right text-sm font-semibold text-gray-700">現價</th>
                  <th className="px-6 py-3 text-right text-sm font-semibold text-gray-700">市值</th>
                  <th className="px-6 py-3 text-right text-sm font-semibold text-gray-700">損益</th>
                  <th className="px-6 py-3 text-center text-sm font-semibold text-gray-700">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr className="border-b hover:bg-gray-50">
                  <td className="px-6 py-4">TSMC (台積電)</td>
                  <td className="px-6 py-4">2330</td>
                  <td className="px-6 py-4 text-right font-semibold">10</td>
                  <td className="px-6 py-4 text-right">NT$2010.00</td>
                  <td className="px-6 py-4 text-right font-semibold">NT$2015.00</td>
                  <td className="px-6 py-4 text-right font-semibold">NT$20,150.00</td>
                  <td className="px-6 py-4 text-right font-semibold text-green-600">+NT$50.00</td>
                  <td className="px-6 py-4 text-center">
                    <Link href="/stock/2330" className="text-indigo-600 hover:underline">
                      查看
                    </Link>
                  </td>
                </tr>
              </tbody>
            </table>
            <div className="px-6 py-4 bg-gray-50 text-gray-600 text-sm">
              共 1 筆持股
            </div>
          </div>
        )}

        {/* Orders Tab */}
        {activeTab === 'orders' && (
          <div className="bg-white rounded-lg shadow-lg overflow-hidden">
            <table className="w-full">
              <thead className="bg-gray-100 border-b">
                <tr>
                  <th className="px-6 py-3 text-left text-sm font-semibold text-gray-700">股票</th>
                  <th className="px-6 py-3 text-left text-sm font-semibold text-gray-700">類型</th>
                  <th className="px-6 py-3 text-right text-sm font-semibold text-gray-700">股數</th>
                  <th className="px-6 py-3 text-right text-sm font-semibold text-gray-700">價格</th>
                  <th className="px-6 py-3 text-left text-sm font-semibold text-gray-700">時間</th>
                  <th className="px-6 py-3 text-left text-sm font-semibold text-gray-700">狀態</th>
                </tr>
              </thead>
              <tbody>
                {mockOrders.map(order => (
                  <tr key={order.id} className="border-b hover:bg-gray-50">
                    <td className="px-6 py-4">{order.symbol}</td>
                    <td className="px-6 py-4">
                      <span
                        className={`px-2 py-1 rounded text-sm font-semibold ${
                          order.type === 'buy'
                            ? 'bg-green-100 text-green-800'
                            : 'bg-red-100 text-red-800'
                        }`}
                      >
                        {order.type === 'buy' ? '買入' : '賣出'}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-right">{order.shares}</td>
                    <td className="px-6 py-4 text-right">NT${order.price.toFixed(2)}</td>
                    <td className="px-6 py-4">{order.date}</td>
                    <td className="px-6 py-4">
                      <span
                        className={`px-2 py-1 rounded text-sm font-semibold ${
                          order.status === 'filled'
                            ? 'bg-blue-100 text-blue-800'
                            : 'bg-yellow-100 text-yellow-800'
                        }`}
                      >
                        {order.status === 'filled' ? '已成交' : '待成交'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="px-6 py-4 bg-gray-50 text-gray-600 text-sm">
              共 {mockOrders.length} 筆訂單
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
