import React, { useState, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import api from '../lib/api'

interface Props {
  stockId: string
  stockName?: string
}

interface AnalysisResult {
  analysis: string
  model: string
  cached_at: string | null
  from_cache: boolean
  date: string
}

export default function StockAIAnalysis({ stockId, stockName }: Props) {
  const [result, setResult] = useState<AnalysisResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setResult(null)
    setError(null)
  }, [stockId])

  async function fetchAnalysis(refresh = false) {
    setLoading(true)
    setError(null)
    try {
      const res = await api.get(`/stocks/${stockId}/ai-analysis${refresh ? '?refresh=true' : ''}`)
      setResult(res.data)
    } catch (e: any) {
      setError(e?.response?.data?.detail || '分析失敗，請稍後再試')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="bg-zinc-900/60 backdrop-blur-md rounded-none sm:rounded-2xl shadow-lg border-b border-x-0 sm:border border-zinc-800/60 p-4 sm:p-6 mb-0 sm:mb-6">
      <div className="flex items-center justify-between mb-3">
        <p className="text-base font-bold text-amber-400">
          AI 智慧解讀
        </p>
        {result && (
          <button
            onClick={() => fetchAnalysis(true)}
            disabled={loading}
            className="text-xs text-zinc-500 hover:text-violet-400 transition-colors disabled:opacity-40"
          >
            重新分析
          </button>
        )}
      </div>

      {/* 尚未觸發 */}
      {!result && !loading && !error && (
        <button
          onClick={() => fetchAnalysis(false)}
          className="w-full py-3 rounded-lg border border-violet-500/30 bg-violet-500/10 text-violet-300 text-sm font-medium hover:bg-violet-500/20 transition-colors"
        >
          🤖 請 AI 解讀這支股票
        </button>
      )}

      {/* 載入中 skeleton */}
      {loading && (
        <div className="space-y-2 animate-pulse">
          <div className="h-3 bg-zinc-700 rounded w-full" />
          <div className="h-3 bg-zinc-700 rounded w-5/6" />
          <div className="h-3 bg-zinc-700 rounded w-4/6 mt-3" />
          <div className="h-3 bg-zinc-700 rounded w-full" />
          <div className="h-3 bg-zinc-700 rounded w-3/4 mt-3" />
          <div className="h-3 bg-zinc-700 rounded w-5/6" />
        </div>
      )}

      {/* 錯誤 */}
      {error && !loading && (
        <div className="text-rose-400 text-sm py-2">
          ❌ {error}
          <button
            onClick={() => fetchAnalysis(false)}
            className="ml-3 text-zinc-400 hover:text-zinc-200 underline text-xs"
          >
            重試
          </button>
        </div>
      )}

      {/* 分析結果 */}
      {result && !loading && (() => {
        // 解析分數：**分數：XX／100**
        const scoreMatch = result.analysis.match(/\*\*分數[：:]\s*(\d+)[／/]100\*\*/)
        const score = scoreMatch ? parseInt(scoreMatch[1]) : null
        const scoreColor = score === null ? 'text-zinc-400'
          : score >= 70 ? 'text-rose-400'
          : score >= 40 ? 'text-amber-400'
          : 'text-emerald-400'
        // 雙向條：以 50 為中心，計算偏移量與方向
        const offset = score !== null ? score - 50 : 0   // -50 ~ +50
        const barWidth = Math.abs(offset) * 2            // 0% ~ 100% of half-width
        const isBullish = offset >= 0

        return (
        <div>
          {/* 分數視覺化 */}
          {score !== null && (
            <div className="mb-4 p-3 bg-zinc-900/40 rounded-lg border border-zinc-700/60">
              <div className="flex items-center gap-3">
                {/* 左：大號分數 */}
                <span className={`text-3xl font-bold font-mono leading-none shrink-0 ${scoreColor}`}>{score}</span>
                {/* 右：bar + meta */}
                <div className="flex-1 min-w-0">
                  {/* 看跌 ── bar ── 看漲 */}
                  <div className="flex items-center gap-1.5 mb-1.5">
                    <span className="text-[10px] text-emerald-500 shrink-0">看跌</span>
                    <div className="flex flex-1 h-1.5">
                      <div className="flex-1 bg-zinc-700 rounded-l-full overflow-hidden flex justify-end">
                        {!isBullish && (
                          <div className="h-full bg-emerald-500" style={{ width: `${barWidth}%` }} />
                        )}
                      </div>
                      <div className="w-px bg-zinc-500 shrink-0" />
                      <div className="flex-1 bg-zinc-700 rounded-r-full overflow-hidden">
                        {isBullish && (
                          <div className="h-full bg-rose-500" style={{ width: `${barWidth}%` }} />
                        )}
                      </div>
                    </div>
                    <span className="text-[10px] text-rose-400 shrink-0">看漲</span>
                  </div>
                  {/* 股名左、日期右 */}
                  <div className="flex items-center justify-between text-xs text-zinc-500">
                    <div className="flex items-center gap-1.5">
                      {stockName && <><span className="text-zinc-300">{stockName}</span><span className="text-zinc-400">{stockId}</span></>}
                    </div>
                    <span>{result.date}</span>
                  </div>
                </div>
              </div>
            </div>
          )}
          <ReactMarkdown
            components={{
              h3: ({ children }) => (
                <h3 className="text-zinc-100 font-semibold text-sm mt-4 mb-1.5 first:mt-0">{children}</h3>
              ),
              p: ({ children }) => (
                <p className="text-sm text-zinc-300 leading-relaxed mb-2">{children}</p>
              ),
              strong: ({ children }) => (
                <strong className="text-amber-400 font-semibold">{children}</strong>
              ),
              ul: ({ children }) => (
                <ul className="list-disc list-inside space-y-1 mb-2 text-sm text-zinc-300">{children}</ul>
              ),
              li: ({ children }) => (
                <li className="leading-relaxed">{children}</li>
              ),
              hr: () => <hr className="border-zinc-700 my-3" />,
              code: ({ children }) => (
                <code className="text-xs text-zinc-400 bg-zinc-900 px-1 rounded">{children}</code>
              ),
              pre: ({ children }) => (
                <pre className="text-xs text-zinc-400 bg-zinc-900 p-2 rounded overflow-x-auto mb-2">{children}</pre>
              ),
            }}
          >
            {result.analysis}
          </ReactMarkdown>
          <div className="mt-4 flex items-center justify-between text-xs text-zinc-600">
            <span>
              {result.from_cache
                ? `資料來自今日快取・${result.cached_at}`
                : `剛剛生成・${result.date}`}
            </span>
            <span>{result.model}</span>
          </div>
        </div>
        )
      })()}
    </div>
  )
}
