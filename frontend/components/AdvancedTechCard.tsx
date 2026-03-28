import { useState, useEffect } from 'react'
import api from '../lib/api'

interface MaDeductionItem {
  current_price: number
  deduction_price: number | null
  ma_value: number | null
  deviation_pct: number | null
  trend: 'up' | 'down' | null
}

interface AdvancedIndicators {
  stock_id: string
  current_price: number
  bias: { bias5: number | null; bias10: number | null; bias20: number | null; bias60: number | null }
  ma_deduction: { ma5: MaDeductionItem; ma20: MaDeductionItem }
  composite_score: number
}

const BIAS_THRESHOLDS: Record<string, number> = { bias5: 5, bias10: 8, bias20: 10, bias60: 15 }
const BIAS_LABELS: Record<string, string> = { bias5: 'BIAS 5', bias10: 'BIAS 10', bias20: 'BIAS 20', bias60: 'BIAS 60' }

function biasColor(key: string, val: number | null): string {
  if (val === null) return 'text-zinc-500'
  const thr = BIAS_THRESHOLDS[key]
  if (val > thr) return 'text-rose-400'
  if (val < -thr) return 'text-emerald-400'
  if (val > 0) return 'text-rose-300'
  return 'text-emerald-300'
}

function biasWarning(key: string, val: number | null): string | null {
  if (val === null) return null
  const thr = BIAS_THRESHOLDS[key]
  if (val > thr) return '超漲警示'
  if (val < -thr) return '超跌警示'
  return null
}

function scoreLabel(score: number): { text: string; color: string } {
  if (score >= 76) return { text: '強勢', color: 'text-emerald-400' }
  if (score >= 56) return { text: '偏強', color: 'text-emerald-300' }
  if (score >= 46) return { text: '中性', color: 'text-zinc-400' }
  if (score >= 26) return { text: '偏弱', color: 'text-amber-400' }
  return { text: '弱勢', color: 'text-rose-400' }
}

function scoreBarColor(score: number): string {
  if (score >= 66) return 'bg-emerald-500'
  if (score >= 46) return 'bg-zinc-500'
  return 'bg-rose-500'
}

export default function AdvancedTechCard({ stockId }: { stockId: string }) {
  const [data, setData] = useState<AdvancedIndicators | null>(null)
  const [showDetail, setShowDetail] = useState(false)

  useEffect(() => {
    if (!stockId) return
    api.get(`/stocks/${stockId}/advanced-indicators`).then(r => setData(r.data)).catch(() => {})
  }, [stockId])

  if (!data) return null

  const { bias, ma_deduction, composite_score } = data
  const { text: scoreText, color: scoreColor } = scoreLabel(composite_score)

  return (
    <div className="bg-zinc-900/60 backdrop-blur-md rounded-none sm:rounded-2xl border-b border-x-0 sm:border border-zinc-800/60 p-4 sm:p-6 mb-0 sm:mb-6">
      <div className="flex items-center justify-between mb-3">
        <p className="text-sm font-bold text-zinc-500 uppercase tracking-widest">進階技術分析</p>
        <button
          onClick={() => setShowDetail(v => !v)}
          className="text-sm text-amber-400 hover:text-amber-300 transition-colors flex items-center gap-1"
        >
          {showDetail ? '收起' : '查看明細'}
          <span className={`transition-transform inline-block ${showDetail ? 'rotate-90' : ''}`}>›</span>
        </button>
      </div>

      {/* ── 綜合評等 ── */}
      <div className="flex items-center justify-between mb-2">
        <span className="text-base text-zinc-400">綜合評等</span>
        <div className="text-right">
          <span className={`font-mono font-bold text-base ${scoreColor}`}>{scoreText}</span>
          <span className="text-zinc-400 text-xs ml-1.5">{composite_score}/100</span>
        </div>
      </div>
      <div className="w-full h-1.5 bg-zinc-800 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${scoreBarColor(composite_score)}`}
          style={{ width: `${composite_score}%` }}
        />
      </div>
      <div className="flex justify-between text-xs text-zinc-500 mt-0.5 mb-3">
        <span>弱勢</span><span>中性</span><span>強勢</span>
      </div>

      {/* ── 明細（收合） ── */}
      {showDetail && (
        <div className="mt-2 pt-2 border-t border-zinc-800/40 space-y-1.5">
          {/* BIAS 四期：一行 4 chips */}
          <div className="flex gap-2">
            {(['bias5', 'bias10', 'bias20', 'bias60'] as const).map(key => {
              const val = bias[key]
              const warn = biasWarning(key, val)
              return (
                <div key={key} className="flex-1 bg-zinc-800/50 rounded-lg px-2 py-1.5 text-center">
                  <p className="text-xs text-zinc-400 mb-0.5">{BIAS_LABELS[key]}</p>
                  <p className={`font-mono text-sm font-semibold ${biasColor(key, val)}`}>
                    {val !== null ? `${val > 0 ? '+' : ''}${val.toFixed(1)}%` : '---'}
                  </p>
                  {warn && <p className="text-[10px] text-amber-400 leading-none mt-0.5">{warn}</p>}
                </div>
              )
            })}
          </div>

          {/* MA 扣抵：2 行緊湊 */}
          {(['ma5', 'ma20'] as const).map(key => {
            const item = ma_deduction[key]
            const label = key === 'ma5' ? 'MA5' : 'MA20'
            const trendArrow = item.trend === 'up' ? '↑' : item.trend === 'down' ? '↓' : ''
            const trendColor = item.trend === 'up' ? 'text-emerald-400' : 'text-rose-400'
            return (
              <div key={key} className="flex items-center justify-between bg-zinc-800/50 rounded-lg px-2 py-1.5">
                <span className="text-sm text-zinc-300">{label} 扣抵</span>
                <div className="flex items-center gap-2 text-sm font-mono">
                  <span className="text-zinc-400">扣抵 {item.deduction_price?.toFixed(0) ?? '---'}</span>
                  {item.deviation_pct !== null && (
                    <span className={`font-semibold ${trendColor}`}>
                      {item.deviation_pct > 0 ? '+' : ''}{item.deviation_pct.toFixed(1)}% {trendArrow}
                    </span>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
