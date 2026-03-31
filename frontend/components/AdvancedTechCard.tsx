import { useState, useEffect } from 'react'
import api from '../lib/api'
import EducationalHint from './EducationalHint'
import KDIndicator from './KDIndicator'

interface MaDeductionItem {
  current_price: number
  deduction_price: number | null
  ma_value: number | null
  deviation_pct: number | null
  trend: 'up' | 'down' | null
}

interface MacdData {
  dif: number | null
  dea: number | null
  osc: number | null
  signal: string | null
}

interface AdvancedIndicators {
  stock_id: string
  current_price: number
  bias: { bias5: number | null; bias10: number | null; bias20: number | null; bias60: number | null }
  ma_deduction: { ma5: MaDeductionItem; ma20: MaDeductionItem }
  macd: MacdData | null
  vol_ratio: number | null
  composite_score: number
}

interface Props {
  stockId: string
  indicators?: { ma20?: number; rsi?: number; bb_upper?: number; bb_lower?: number } | null
  displayPrice?: number | null
  quoteDate?: string | null
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
  if (score >= 76) return { text: '強勢', color: 'text-rose-400' }
  if (score >= 56) return { text: '偏強', color: 'text-rose-300' }
  if (score >= 46) return { text: '中性', color: 'text-zinc-400' }
  if (score >= 26) return { text: '偏弱', color: 'text-amber-400' }
  return { text: '弱勢', color: 'text-emerald-400' }
}

function scoreBarColor(score: number): string {
  if (score >= 66) return 'bg-rose-500'
  if (score >= 46) return 'bg-zinc-500'
  return 'bg-emerald-500'
}

function volRatioDisplay(ratio: number | null): { label: string; color: string } | null {
  if (ratio === null) return null
  if (ratio >= 3.0) return { label: '爆量', color: 'text-amber-400' }
  if (ratio >= 1.5) return { label: '放量', color: 'text-rose-400' }
  if (ratio >= 0.8) return { label: '正常', color: 'text-zinc-400' }
  if (ratio >= 0.5) return { label: '縮量', color: 'text-zinc-400' }
  return { label: '極縮量', color: 'text-cyan-400' }
}

export default function AdvancedTechCard({ stockId, indicators, displayPrice, quoteDate }: Props) {
  const [data, setData] = useState<AdvancedIndicators | null>(null)
  const [showDetail, setShowDetail] = useState(false)

  useEffect(() => {
    if (!stockId) return
    api.get(`/stocks/${stockId}/advanced-indicators`).then(r => setData(r.data)).catch(() => {})
  }, [stockId])

  // 技術面信號
  const price = displayPrice ?? null
  const ma20 = indicators?.ma20
  const rsi = indicators?.rsi
  const bbUpper = indicators?.bb_upper
  const bbLower = indicators?.bb_lower

  const trendSignal = price && ma20 ? (() => {
    const diff = (price / ma20 - 1) * 100
    return diff >= 0
      ? { label: '站上 MA20', sub: `高於均線 +${diff.toFixed(1)}%`, color: 'text-rose-400' }
      : { label: '跌破 MA20', sub: `低於均線 ${diff.toFixed(1)}%`, color: 'text-emerald-400' }
  })() : null

  const rsiSignal = rsi ? (() => {
    if (rsi > 70) return { label: `RSI ${rsi.toFixed(1)}`, sub: '超買區，注意回檔', color: 'text-amber-400' }
    if (rsi > 50) return { label: `RSI ${rsi.toFixed(1)}`, sub: '中性偏強', color: 'text-rose-400' }
    if (rsi > 30) return { label: `RSI ${rsi.toFixed(1)}`, sub: '中性偏弱', color: 'text-zinc-400' }
    return { label: `RSI ${rsi.toFixed(1)}`, sub: '超賣區，留意反彈', color: 'text-cyan-400' }
  })() : null

  const bbSignal = price && bbUpper && bbLower ? (() => {
    const pos = (price - bbLower) / (bbUpper - bbLower)
    const pct = (pos * 100).toFixed(0)
    if (pos > 0.85) return { label: `布林 ${pct}%`, sub: '接近上軌，注意追高', color: 'text-amber-400' }
    if (pos > 0.5)  return { label: `布林 ${pct}%`, sub: '通道上半段，偏多', color: 'text-rose-400' }
    if (pos > 0.15) return { label: `布林 ${pct}%`, sub: '通道下半段，偏弱', color: 'text-zinc-400' }
    return { label: `布林 ${pct}%`, sub: '接近下軌，留意支撐', color: 'text-cyan-400' }
  })() : null

  const macdSignal = data?.macd ? (() => {
    const { dif, osc, signal } = data.macd
    if (dif === null || osc === null) return null
    let sub = osc > 0 ? '柱狀翻正，動能轉強' : '柱狀翻負，動能轉弱'
    let color = osc > 0 ? 'text-rose-400' : 'text-emerald-400'
    if (signal) {
      sub = signal === '黃金交叉' ? 'DIF 上穿 DEA，多頭訊號' : 'DIF 下穿 DEA，空頭訊號'
      color = signal === '黃金交叉' ? 'text-rose-400' : 'text-emerald-400'
    }
    return { label: `DIF ${dif.toFixed(2)}`, sub, color }
  })() : null

  const hasSignals = indicators != null
  if (!data && !hasSignals) return null

  const { bias, ma_deduction, composite_score } = data ?? { bias: null, ma_deduction: null, composite_score: null }
  const sl = composite_score != null ? scoreLabel(composite_score) : null

  const volInfo = data?.vol_ratio != null ? volRatioDisplay(data.vol_ratio) : null

  return (
    <div className="bg-zinc-900/60 backdrop-blur-md rounded-none sm:rounded-2xl border-b border-x-0 sm:border border-zinc-800/60 p-4 sm:p-6 mb-0 sm:mb-6">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-baseline gap-2">
          <p className="text-base font-bold text-amber-400">技術面分析</p>
          {quoteDate && (
            <span className="text-xs text-zinc-500">{new Date(quoteDate).toLocaleDateString('zh-TW', { year: 'numeric', month: '2-digit', day: '2-digit' })} 更新</span>
          )}
        </div>
        {(data || hasSignals) && (
          <button
            onClick={() => setShowDetail(v => !v)}
            className="text-sm text-amber-400 hover:text-amber-300 transition-colors flex items-center gap-1"
          >
            {showDetail ? '收起' : '查看明細'}
            <span className={`transition-transform inline-block ${showDetail ? 'rotate-90' : ''}`}>›</span>
          </button>
        )}
      </div>

      {/* ── 綜合評等（始終顯示） ── */}
      {data && sl && composite_score != null && (
        <div>
          <div className="flex items-center justify-between mb-2">
            <span className="text-base text-zinc-400">綜合評等</span>
            <div className="text-right">
              <span className={`font-mono font-bold text-base ${sl.color}`}>{sl.text}</span>
              <span className="text-zinc-400 text-xs ml-1.5">{composite_score}/100</span>
            </div>
          </div>
          <div className="w-full h-1.5 bg-zinc-800 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${scoreBarColor(composite_score)}`}
              style={{ width: `${composite_score}%` }}
            />
          </div>
          <div className="flex justify-between text-xs text-zinc-500 mt-0.5">
            <span>弱勢</span><span>中性</span><span>強勢</span>
          </div>
        </div>
      )}

      {/* ── 明細（展開後） ── */}
      {showDetail && (
        <>
        {/* 核心技術指標（依重要程度排序） */}
        {(hasSignals || data) && (
          <div className="mt-1 pt-1 border-t border-zinc-800/40 space-y-1.5">
            {/* 1. 均線位階 — 最基礎的趨勢判斷 */}
            {trendSignal && (
              <div className="flex items-center justify-between bg-zinc-800/50 rounded-lg px-2 py-1.5">
                <span className="text-sm text-zinc-300 flex items-center gap-1.5">
                  均線位階
                  <EducationalHint glossaryId="ma-indicator" />
                </span>
                <div className="flex items-center gap-2 text-sm font-mono">
                  <span className="text-zinc-400">{trendSignal.sub}</span>
                  <span className={`font-semibold ${trendSignal.color}`}>{trendSignal.label}</span>
                </div>
              </div>
            )}

            {/* 2. MACD — 動能方向與交叉訊號 */}
            {macdSignal && (
              <div className="flex items-center justify-between bg-zinc-800/50 rounded-lg px-2 py-1.5">
                <span className="text-sm text-zinc-300 flex items-center gap-1.5">
                  MACD
                  <EducationalHint glossaryId="macd-indicator" />
                </span>
                <div className="flex items-center gap-2 text-sm font-mono">
                  <span className="text-zinc-400">{macdSignal.sub}</span>
                  <span className={`font-semibold ${macdSignal.color}`}>{macdSignal.label}</span>
                </div>
              </div>
            )}

            {/* 3. KD 指標 — 台股最常用的擺盪指標 */}
            <div className="flex items-center justify-between bg-zinc-800/50 rounded-lg px-2 py-1.5">
              <span className="text-sm text-zinc-300 flex items-center gap-1.5">
                KD 指標
                <EducationalHint glossaryId="kd-indicator" />
              </span>
              <KDIndicator stockId={stockId} />
            </div>

            {/* 4. RSI — 超買超賣判斷 */}
            {rsiSignal && (
              <div className="flex items-center justify-between bg-zinc-800/50 rounded-lg px-2 py-1.5">
                <span className="text-sm text-zinc-300 flex items-center gap-1.5">
                  RSI
                  <EducationalHint glossaryId="rsi-indicator" />
                </span>
                <div className="flex items-center gap-2 text-sm font-mono">
                  <span className="text-zinc-400">{rsiSignal.sub}</span>
                  <span className={`font-semibold ${rsiSignal.color}`}>{rsiSignal.label}</span>
                </div>
              </div>
            )}

            {/* 5. 布林通道 — 波動位置 */}
            {bbSignal && (
              <div className="flex items-center justify-between bg-zinc-800/50 rounded-lg px-2 py-1.5">
                <span className="text-sm text-zinc-300">布林通道</span>
                <div className="flex items-center gap-2 text-sm font-mono">
                  <span className="text-zinc-400">{bbSignal.sub}</span>
                  <span className={`font-semibold ${bbSignal.color}`}>{bbSignal.label}</span>
                </div>
              </div>
            )}

            {/* 6. 成交量比 — 量能確認 */}
            {data?.vol_ratio != null && volInfo && (
              <div className="flex items-center justify-between bg-zinc-800/50 rounded-lg px-2 py-1.5">
                <span className="text-sm text-zinc-300">成交量比</span>
                <div className="flex items-center gap-2 text-sm font-mono">
                  <span className="text-zinc-400">今量 / 5日均量</span>
                  <span className={`font-semibold ${volInfo.color}`}>
                    {data.vol_ratio.toFixed(2)}x {volInfo.label}
                  </span>
                </div>
              </div>
            )}

          {/* BIAS + MA 扣抵 */}
          {data && bias && ma_deduction && (<>
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
                  {warn && <p className="text-xs text-amber-400 leading-none mt-0.5">{warn}</p>}
                </div>
              )
            })}
          </div>

          {/* MA 扣抵：2 行緊湊 */}
          {(['ma5', 'ma20'] as const).map(key => {
            const item = ma_deduction[key]
            const label = key === 'ma5' ? 'MA5' : 'MA20'
            const trendArrow = item.trend === 'up' ? '↑' : item.trend === 'down' ? '↓' : ''
            const trendColor = item.trend === 'up' ? 'text-rose-400' : 'text-emerald-400'
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
          </>)}
          </div>
        )}
        </>
      )}
    </div>
  )
}
