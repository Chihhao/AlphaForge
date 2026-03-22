import React from 'react'
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from 'recharts'

const portfolioData = [
  { name: 'TSMC (2330)', value: 50 },
  { name: 'MediaTek (2454)', value: 30 },
  { name: '現金', value: 20 },
]

const COLORS = ['#f59e0b', '#6366f1', '#3f3f46']

export default function Portfolio() {
  return (
    <div className="flex-grow">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <h1 className="text-3xl font-bold text-gray-100 mb-8 border-l-4 border-amber-400 pl-4">投資組合分析</h1>

        {/* Performance Summary */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
          <div className="bg-zinc-900/40 rounded-xl border border-zinc-800/50 p-5">
            <p className="text-zinc-400 text-sm mb-1">報酬率</p>
            <p className="text-3xl font-bold text-rose-400">+5.00%</p>
            <p className="text-xs text-zinc-600 mt-2">自開始交易以來</p>
          </div>
          <div className="bg-zinc-900/40 rounded-xl border border-zinc-800/50 p-5">
            <p className="text-zinc-400 text-sm mb-1">最大跌幅</p>
            <p className="text-3xl font-bold text-emerald-400">-3.50%</p>
            <p className="text-xs text-zinc-600 mt-2">單日最差表現</p>
          </div>
          <div className="bg-zinc-900/40 rounded-xl border border-zinc-800/50 p-5">
            <p className="text-zinc-400 text-sm mb-1">勝率</p>
            <p className="text-3xl font-bold text-amber-400">66.67%</p>
            <p className="text-xs text-zinc-600 mt-2">獲利交易比例</p>
          </div>
          <div className="bg-zinc-900/40 rounded-xl border border-zinc-800/50 p-5">
            <p className="text-zinc-400 text-sm mb-1">夏普比率</p>
            <p className="text-3xl font-bold text-cyan-400">1.42</p>
            <p className="text-xs text-zinc-600 mt-2">風險調整後報酬</p>
          </div>
        </div>

        {/* Portfolio Composition */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
          <div className="bg-zinc-900/40 rounded-xl border border-zinc-800/50 p-6">
            <h2 className="text-lg font-bold text-gray-100 mb-6">資產配置</h2>
            <ResponsiveContainer width="100%" height={260}>
              <PieChart>
                <Pie
                  data={portfolioData}
                  cx="50%"
                  cy="50%"
                  labelLine={false}
                  label={({ name, value }) => `${name}: ${value}%`}
                  outerRadius={80}
                  dataKey="value"
                >
                  {portfolioData.map((_, index) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{ background: '#18181b', border: '1px solid #3f3f46', borderRadius: 8 }}
                  labelStyle={{ color: '#a1a1aa' }}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>

          <div className="bg-zinc-900/40 rounded-xl border border-zinc-800/50 p-6">
            <h2 className="text-lg font-bold text-gray-100 mb-6">績效統計</h2>
            <div className="space-y-3">
              {[
                { label: '總交易次數', value: '3', color: 'text-zinc-200' },
                { label: '獲利交易', value: '2', color: 'text-rose-400' },
                { label: '虧損交易', value: '1', color: 'text-emerald-400' },
                { label: '平均獲利', value: '+2,500', color: 'text-rose-400' },
                { label: '平均虧損', value: '-1,200', color: 'text-emerald-400' },
                { label: '最大獲利', value: '+3,500', color: 'text-rose-400' },
                { label: '最大虧損', value: '-1,500', color: 'text-emerald-400' },
              ].map((item, i) => (
                <div key={i} className={`flex justify-between ${i === 2 || i === 4 ? '' : ''}`}>
                  <span className="text-zinc-400 text-sm">{item.label}</span>
                  <span className={`font-semibold text-sm ${item.color}`}>{item.value}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Holdings Detail */}
        <div className="bg-zinc-900/40 rounded-xl border border-zinc-800/50 overflow-hidden">
          <div className="p-5 border-b border-zinc-800">
            <h2 className="text-lg font-bold text-zinc-100">持股詳情</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-zinc-800">
                <tr>
                  {['股票', '持股', '成本', '現價', '市值', '利潤', '報酬率'].map(h => (
                    <th key={h} className={`px-5 py-3 ${h === '股票' ? 'text-left' : 'text-right'} font-medium text-zinc-500 whitespace-nowrap`}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
                  <td className="px-5 py-4 text-zinc-200 font-medium">台積電 (2330)</td>
                  <td className="px-5 py-4 text-right text-zinc-300">10</td>
                  <td className="px-5 py-4 text-right font-mono text-zinc-400">2,010</td>
                  <td className="px-5 py-4 text-right font-mono text-zinc-200">2,015</td>
                  <td className="px-5 py-4 text-right font-mono font-semibold text-zinc-200">20,150</td>
                  <td className="px-5 py-4 text-right font-mono font-semibold text-rose-400">+50</td>
                  <td className="px-5 py-4 text-right font-mono font-semibold text-rose-400">+0.25%</td>
                </tr>
                <tr className="hover:bg-zinc-800/30">
                  <td className="px-5 py-4 text-zinc-200 font-medium">聯發科 (2454)</td>
                  <td className="px-5 py-4 text-right text-zinc-300">5</td>
                  <td className="px-5 py-4 text-right font-mono text-zinc-400">850</td>
                  <td className="px-5 py-4 text-right font-mono text-zinc-200">890</td>
                  <td className="px-5 py-4 text-right font-mono font-semibold text-zinc-200">4,450</td>
                  <td className="px-5 py-4 text-right font-mono font-semibold text-rose-400">+200</td>
                  <td className="px-5 py-4 text-right font-mono font-semibold text-rose-400">+4.71%</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div className="px-5 py-3 border-t border-zinc-800 text-zinc-500 text-xs">
            共 2 筆持股 · 示例資料僅供展示
          </div>
        </div>
      </div>
    </div>
  )
}
