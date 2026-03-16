import React, { useState } from 'react'
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
    <div className="bg-gray-800 rounded-none sm:rounded-lg shadow-lg border-b border-x-0 sm:border border-gray-700 p-4 sm:p-6 mb-0 sm:mb-6">
      <div className="flex items-center justify-between mb-3">
        <p className="text-sm font-bold text-gray-500 uppercase tracking-widest border-l-2 border-violet-500 pl-1.5">
          AI 智慧解讀
        </p>
        {result && (
          <button
            onClick={() => fetchAnalysis(true)}
            disabled={loading}
            className="text-xs text-gray-500 hover:text-violet-400 transition-colors disabled:opacity-40"
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
          <div className="h-3 bg-gray-700 rounded w-full" />
          <div className="h-3 bg-gray-700 rounded w-5/6" />
          <div className="h-3 bg-gray-700 rounded w-4/6 mt-3" />
          <div className="h-3 bg-gray-700 rounded w-full" />
          <div className="h-3 bg-gray-700 rounded w-3/4 mt-3" />
          <div className="h-3 bg-gray-700 rounded w-5/6" />
        </div>
      )}

      {/* 錯誤 */}
      {error && !loading && (
        <div className="text-rose-400 text-sm py-2">
          ❌ {error}
          <button
            onClick={() => fetchAnalysis(false)}
            className="ml-3 text-gray-400 hover:text-gray-200 underline text-xs"
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
        const scoreColor = score === null ? 'text-gray-400'
          : score >= 70 ? 'text-rose-400'
          : score >= 40 ? 'text-amber-400'
          : 'text-emerald-400'
        const barColor = score === null ? 'bg-gray-600'
          : score >= 70 ? 'bg-rose-500'
          : score >= 40 ? 'bg-amber-500'
          : 'bg-emerald-500'

        return (
        <div>
          {/* 分數視覺化 */}
          {score !== null && (
            <div className="mb-4 p-3 bg-gray-900/60 rounded-lg border border-gray-700">
              <div className="flex items-center gap-3">
                {/* 左：分數 */}
                <span className={`text-3xl font-bold font-mono leading-none ${scoreColor}`}>{score}</span>
                {/* 中：進度條 + meta */}
                <div className="flex-1 min-w-0">
                  <div className="h-1.5 bg-gray-700 rounded-full overflow-hidden mb-1.5">
                    <div className={`h-full rounded-full ${barColor}`} style={{ width: `${score}%` }} />
                  </div>
                  <div className="flex items-center gap-1.5 text-xs text-gray-500">
                    <span>AI 看漲分數</span>
                    {stockName && <><span>·</span><span className="text-gray-300">{stockName}</span><span className="text-gray-600">{stockId}</span></>}
                    <span>·</span>
                    <span>{result.date}</span>
                  </div>
                </div>
              </div>
            </div>
          )}
          <ReactMarkdown
            components={{
              h3: ({ children }) => (
                <h3 className="text-gray-100 font-semibold text-sm mt-4 mb-1.5 first:mt-0">{children}</h3>
              ),
              p: ({ children }) => (
                <p className="text-sm text-gray-300 leading-relaxed mb-2">{children}</p>
              ),
              strong: ({ children }) => (
                <strong className="text-amber-400 font-semibold">{children}</strong>
              ),
              ul: ({ children }) => (
                <ul className="list-disc list-inside space-y-1 mb-2 text-sm text-gray-300">{children}</ul>
              ),
              li: ({ children }) => (
                <li className="leading-relaxed">{children}</li>
              ),
              hr: () => <hr className="border-gray-700 my-3" />,
              code: ({ children }) => (
                <code className="text-xs text-gray-400 bg-gray-900 px-1 rounded">{children}</code>
              ),
              pre: ({ children }) => (
                <pre className="text-xs text-gray-400 bg-gray-900 p-2 rounded overflow-x-auto mb-2">{children}</pre>
              ),
            }}
          >
            {result.analysis}
          </ReactMarkdown>
          <div className="mt-4 flex items-center justify-between text-xs text-gray-600">
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
