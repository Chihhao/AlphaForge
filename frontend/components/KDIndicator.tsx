import React, { useState, useEffect } from 'react'
import api from '../lib/api'

interface KDStatusData {
  k: number
  d: number
  status: string
  signal: string | null
}

interface KDIndicatorProps {
  stockId: string
}

const KDIndicator: React.FC<KDIndicatorProps> = ({ stockId }) => {
  const [kdStatus, setKdStatus] = useState<KDStatusData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!stockId) return
    const fetchKD = async () => {
      setLoading(true)
      setError(null)
      try {
        const res = await api.get(`/indicators/kd/${stockId}/status`)
        setKdStatus(res.data)
      } catch (e: any) {
        console.error('KD fetch error:', e)
        setError('暫無數據')
      } finally {
        setLoading(false)
      }
    }
    fetchKD()
  }, [stockId])

  if (loading) {
    return <span className="font-semibold text-gray-500 animate-pulse">載入中...</span>
  }

  if (error || !kdStatus) {
    return <span className="font-semibold text-gray-500">{error || '---'}</span>
  }

  const { k, d, status, signal } = kdStatus

  // 數值顏色
  const getColor = (val: number) => {
    if (val > 80) return 'text-red-400'
    if (val < 20) return 'text-emerald-400'
    return 'text-amber-400'
  }

  // 只有「非中性」才需要額外標記
  const isNoteworthy = status.includes('超買') || status.includes('超賣')

  return (
    <span className="inline-flex items-center gap-1.5">
      {/* K / D 數值 */}
      <span className={`font-semibold font-mono ${getColor(k)}`}>
        K:{k.toFixed(0)} / D:{d.toFixed(0)}
      </span>

      {/* 超買超賣時才顯示狀態 */}
      {isNoteworthy && (
        <>
          <span className="text-zinc-600">·</span>
          <span className={`font-semibold ${status.includes('超買') ? 'text-red-400' : 'text-emerald-400'}`}>
            {status.includes('超買') ? '超買' : '超賣'}
          </span>
        </>
      )}

      {/* 交叉訊號 */}
      {signal && (
        <>
          <span className="text-zinc-600">·</span>
          <span className={`font-semibold ${signal === '黃金交叉' ? 'text-emerald-400' : 'text-red-400'}`}>
            {signal}
          </span>
        </>
      )}
    </span>
  )
}

export default KDIndicator
