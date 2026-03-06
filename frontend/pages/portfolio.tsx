import React from 'react'
import Link from 'next/link'
import { PieChart, Pie, Cell, ResponsiveContainer, Legend, Tooltip } from 'recharts'

const portfolioData = [
  { name: 'TSMC (2330)', value: 50 },
  { name: 'MediaTek (2454)', value: 30 },
  { name: '現金', value: 20 },
]

const COLORS = ['#4f46e5', '#ec4899', '#10b981']

export default function Portfolio() {
  return (
    <div className="flex-grow">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <h1 className="text-3xl font-bold text-gray-100 mb-8 border-l-4 border-emerald-400 pl-4">投資組合分析</h1>
        {/* Performance Summary */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
          <div className="bg-zinc-900/40 backdrop-blur-md rounded-lg shadow-xl border border-zinc-800/50 p-6 hover:border-zinc-700/80 transition-all">
            <p className="text-gray-400 text-sm mb-1">報酬率</p>
            <p className="text-3xl font-bold text-green-500">+5.00%</p>
            <p className="text-xs text-gray-500 mt-2">自開始交易以來</p>
          </div>
          <div className="bg-gray-800 rounded-lg shadow border border-gray-700 p-6">
            <p className="text-gray-400 text-sm mb-1">最大跌幅</p>
            <p className="text-3xl font-bold text-red-500">-3.50%</p>
            <p className="text-xs text-gray-500 mt-2">單日最差表現</p>
          </div>
          <div className="bg-gray-800 rounded-lg shadow border border-gray-700 p-6">
            <p className="text-gray-400 text-sm mb-1">勝率</p>
            <p className="text-3xl font-bold text-blue-500">66.67%</p>
            <p className="text-xs text-gray-500 mt-2">獲利交易比例</p>
          </div>
          <div className="bg-gray-800 rounded-lg shadow border border-gray-700 p-6">
            <p className="text-gray-400 text-sm mb-1">夏普比率</p>
            <p className="text-3xl font-bold text-purple-400">1.42</p>
            <p className="text-xs text-gray-500 mt-2">風險調整後報酬</p>
          </div>
        </div>

        {/* Portfolio Composition */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 mb-8">
          {/* Pie Chart */}
          <div className="bg-zinc-900/40 backdrop-blur-md rounded-lg shadow-2xl border border-zinc-800/50 p-6">
            <h2 className="text-xl font-bold text-gray-100 mb-6">資產配置</h2>
            <ResponsiveContainer width="100%" height={300}>
              <PieChart>
                <Pie
                  data={portfolioData}
                  cx="50%"
                  cy="50%"
                  labelLine={false}
                  label={({ name, value }) => `${name}: ${value}%`}
                  outerRadius={80}
                  fill="#8884d8"
                  dataKey="value"
                >
                  {portfolioData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>

          {/* Statistics */}
          <div className="bg-zinc-900/40 backdrop-blur-md rounded-lg shadow-2xl border border-zinc-800/50 p-6">
            <h2 className="text-xl font-bold text-gray-100 mb-6">績效統計</h2>
            <div className="space-y-4">
              <div className="flex justify-between">
                <span className="text-gray-400">總交易次數</span>
                <span className="font-semibold">3</span>
              </div>
              <div className="flex justify-between border-t border-gray-700 pt-4">
                <span className="text-gray-400">獲利交易</span>
                <span className="font-semibold text-green-500">2</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">虧損交易</span>
                <span className="font-semibold text-red-500">1</span>
              </div>
              <div className="flex justify-between border-t border-gray-700 pt-4">
                <span className="text-gray-400">平均獲利</span>
                <span className="font-semibold text-green-500">+2,500</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">平均虧損</span>
                <span className="font-semibold text-red-500">-1,200</span>
              </div>
              <div className="flex justify-between border-t border-gray-700 pt-4">
                <span className="text-gray-400">最大獲利</span>
                <span className="font-semibold">3,500</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">最大虧損</span>
                <span className="font-semibold">-1,500</span>
              </div>
            </div>
          </div>
        </div>

        {/* Holdings Detail */}
        <div className="bg-zinc-900/40 backdrop-blur-md rounded-lg shadow-2xl border border-zinc-800/50 overflow-hidden">
          <div className="p-6 border-b border-gray-700">
            <h2 className="text-xl font-bold text-gray-100">持股詳情</h2>
          </div>
          <table className="w-full">
            <thead className="bg-gray-700 border-b border-gray-600">
              <tr>
                <th className="px-6 py-3 text-left text-sm font-semibold text-gray-200">股票</th>
                <th className="px-6 py-3 text-right text-sm font-semibold text-gray-200">持股</th>
                <th className="px-6 py-3 text-right text-sm font-semibold text-gray-200">成本</th>
                <th className="px-6 py-3 text-right text-sm font-semibold text-gray-200">現價</th>
                <th className="px-6 py-3 text-right text-sm font-semibold text-gray-200">市值</th>
                <th className="px-6 py-3 text-right text-sm font-semibold text-gray-200">利潤</th>
                <th className="px-6 py-3 text-right text-sm font-semibold text-gray-200">報酬率</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-b border-gray-700 hover:bg-gray-700">
                <td className="px-6 py-4">TSMC (2330)</td>
                <td className="px-6 py-4 text-right">10</td>
                <td className="px-6 py-4 text-right">2,010</td>
                <td className="px-6 py-4 text-right">2,015</td>
                <td className="px-6 py-4 text-right font-semibold">20,150</td>
                <td className="px-6 py-4 text-right font-semibold text-green-500">+50</td>
                <td className="px-6 py-4 text-right font-semibold text-green-500">+0.25%</td>
              </tr>
              <tr className="hover:bg-gray-700">
                <td className="px-6 py-4">MediaTek (2454)</td>
                <td className="px-6 py-4 text-right">5</td>
                <td className="px-6 py-4 text-right">850.0</td>
                <td className="px-6 py-4 text-right">890.0</td>
                <td className="px-6 py-4 text-right font-semibold">4,450</td>
                <td className="px-6 py-4 text-right font-semibold text-green-500">+200.0</td>
                <td className="px-6 py-4 text-right font-semibold text-green-500">+4.71%</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
