import React, { useState, useEffect } from 'react'
import { useRouter } from 'next/router'
import Link from 'next/link'
import dynamic from 'next/dynamic'
import api from '../../lib/api'
import KDIndicator from '../../components/KDIndicator'
import EducationalHint from '../../components/EducationalHint'
import { formatPrice } from '../../lib/formatters'

const TVChart = dynamic(() => import('../../components/TVChart'), { ssr: false })

export default function StockDetail() {
  const router = useRouter()
  const { id } = router.query

  const [interval, setInterval] = useState<'1m' | '5m' | '15m' | '1h' | '1d' | '1wk' | '1mo'>('15m')
  const [quote, setQuote] = useState<any>(null)
  const [chartData, setChartData] = useState<Array<any>>([])
  const [indicators, setIndicators] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [subChart, setSubChart] = useState<'volume' | 'rsi' | 'bias'>('volume')

  useEffect(() => {
    if (!id) return

    const fetchData = async () => {
      setLoading(true)
      try {
        // Fetch quote data for the current id
        const qres = await api.get(`/stocks/${id}/quote`)
        setQuote(qres.data)

        // 自動根據頻率決定抓取範圍，確保有足夠的 (300+) 筆資料
        // 1m: 7d (yfinance 限制)
        // 5m, 15m: 60d (yfinance 限制)
        // 1h: 2y
        // 1d: 5y
        // 1wk, 1mo: max
        let period = '5y';
        if (interval === '1m') period = '7d';
        else if (interval === '5m' || interval === '15m') period = '60d';
        else if (interval === '1h') period = '2y';
        else if (interval === '1wk' || interval === '1mo') period = 'max';

        const kres = await api.get(`/stocks/${id}/kline?period=${period}&interval=${interval}`)
        const isIntraday = ['1m', '5m', '15m', '1h'].includes(interval);

        const kd = kres.data
        const rawData = (kd.data || []).map((r: any, index: number) => {
          const date = new Date(r.date);
          if (isNaN(date.getTime())) return null;

          // 如果沒有成交量且價格沒動，視為無效跳空點，過濾掉以消除水平線
          if (r.volume === 0 && r.open === r.close && r.high === r.low) return null;
          if (r.open == null || r.high == null || r.low == null || r.close == null) return null;

          const ts = Math.floor(date.getTime() / 1000);
          return {
            originalTime: ts,
            open: r.open,
            high: r.high,
            low: r.low,
            close: r.close,
            volume: r.volume,
            rOpen: r.open, // 用於判斷漲跌
          };
        }).filter(Boolean);

        // 嚴格依照時間排序
        rawData.sort((a: any, b: any) => a.originalTime - b.originalTime);

        // 去重並轉為帶有漲跌顏色的格式
        const uniqueData: any[] = [];
        const seenTs = new Set();

        // 核心邏輯：如果是日內資料，使用 uniqueData.length 作為連續索引，確保 100% 緊密
        rawData.forEach((r: any) => {
          if (seenTs.has(r.originalTime)) return;
          seenTs.add(r.originalTime);

          let isUp = r.close > r.open;
          let isDown = r.close < r.open;
          if (r.close === r.open) {
            if (uniqueData.length > 0) {
              const prevClose = uniqueData[uniqueData.length - 1].close;
              isUp = r.close > prevClose;
              isDown = r.close < prevClose;
            } else {
              isUp = true;
            }
          }

          const barColor = isUp ? '#f43f5e' : (isDown ? '#34d399' : '#9ca3af');

          // 實施「極簡整數序列」方案 (Version 7)
          // 這是最簡單、最穩定的做法：完全放棄日曆物流，直接使用 0, 1, 2... 序列
          // 配合 TVChart 的 reverse lookup，這能保證 100% 的等邊緊湊排列
          const timeValue = isIntraday ? uniqueData.length : r.originalTime;

          uniqueData.push({
            ...r,
            time: timeValue,
            isUp: isUp || !isDown,
            color: barColor,
            wickColor: barColor,
            borderColor: barColor,
          });
        });

        // 加載指標
        const ires = await api.get(`/stocks/${id}/indicators?period=${period}&interval=${interval}`)
        const indData = ires.data
        const indMap = new Map()
        if (indData.data) {
          indData.data.forEach((ind: any) => {
            const date = new Date(ind.date)
            if (!isNaN(date.getTime())) {
              indMap.set(Math.floor(date.getTime() / 1000), ind)
            }
          })
        }

        uniqueData.forEach(d => {
          const ind = indMap.get(d.originalTime)
          if (ind) {
            d.rsi = ind.rsi
            d.bias = ind.bias_ma20
          }
        })

        setChartData(uniqueData)

        if (indData.data && indData.data.length > 0) {
          // Get the most recent valid indicators
          setIndicators(indData.data[indData.data.length - 1])
        }
      } catch (e) {
        console.error('fetch stock data error', e)
        // 當請求失敗時（例如 yfinance 限制或 404），清除現有數據，避免停留在舊畫面
        setChartData([])
        setIndicators(null)
      } finally {
        setLoading(false)
      }
    }
    fetchData()
  }, [id, interval])

  if (!id) return <div className="text-center py-8">載入中...</div>

  const displayName = quote?.stock_name || `股票 ${id}`
  const displayPrice = quote?.current_price ?? 0
  const displayChange = quote?.change_percent ?? 0

  return (
    <div className="flex-grow">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 sm:py-6">
        {/* Stock Header */}
        <div className="bg-gray-800 rounded-lg shadow-lg border border-gray-700 p-6 mb-4 sm:mb-6">
          <div className="flex justify-between items-start mb-4">
            <div>
              <h1 className="text-3xl font-bold text-gray-100">{displayName}</h1>
              <p className="text-gray-400">股票代號：{id}</p>
            </div>
            <div className="text-right">
              <p className="text-4xl font-bold text-gray-100">{formatPrice(displayPrice)}</p>
              <p className={`text-xl font-semibold ${displayChange >= 0 ? 'text-rose-500' : 'text-emerald-400'}`}>
                {displayChange >= 0 ? '+' : ''}{displayChange.toFixed(2)}%
              </p>
            </div>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-5 gap-4 pt-4 border-t border-gray-700">
            <div>
              <p className="text-sm text-gray-400">開盤</p>
              <p className="text-lg font-semibold">{formatPrice(quote?.open_price)}</p>
            </div>
            <div>
              <p className="text-sm text-gray-400">最高</p>
              <p className="text-lg font-semibold">{formatPrice(quote?.high_price)}</p>
            </div>
            <div>
              <p className="text-sm text-gray-400">最低</p>
              <p className="text-lg font-semibold">{formatPrice(quote?.low_price)}</p>
            </div>
            <div>
              <p className="text-sm text-gray-400">成交量</p>
              <p className="text-lg font-semibold">
                {quote?.volume
                  ? (() => {
                    const lots = quote.volume / 1000;
                    return lots >= 10000
                      ? (lots / 10000).toFixed(2) + ' 萬張'
                      : Math.floor(lots).toLocaleString() + ' 張';
                  })()
                  : '---'}
              </p>
            </div>
            <div>
              <p className="text-sm text-gray-400">庫存/市值</p>
              <p className="text-lg font-semibold">---</p>
            </div>
          </div>
        </div>

        {/* Chart Section */}
        <div className="bg-gray-800 rounded-lg shadow-lg border border-gray-700 p-6 mb-4 sm:mb-6">
          <div className="mb-4">
            <h2 className="text-xl font-bold text-gray-100 mb-4">K線圖表</h2>
            {/* Interval Selector */}
            <div className="space-y-4 mb-6">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider mr-2">K 線頻率</span>
                {(['1m', '5m', '15m', '1h', '1d', '1wk', '1mo'] as const).map(i => {
                  return (
                    <button
                      key={i}
                      onClick={() => setInterval(i)}
                      className={`px-3 py-1.5 rounded-md text-sm font-medium transition-all duration-200 ${interval === i
                        ? 'bg-blue-600 text-white shadow-lg shadow-blue-900/20'
                        : 'bg-gray-700/50 text-gray-400 hover:bg-gray-700 hover:text-gray-200'
                        }`}
                    >
                      {i === '1m' ? '1分' : i === '5m' ? '5分' : i === '15m' ? '15分' : i === '1h' ? '1時' : i === '1d' ? '日' : i === '1wk' ? '週' : '月'}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Sub-chart toggle */}
            <div className="flex flex-wrap items-center gap-2 mb-6">
              <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider mr-2">副圖指標</span>
              {(['volume', 'rsi', 'bias'] as const).map(s => (
                <button
                  key={s}
                  onClick={() => setSubChart(s)}
                  className={`px-3 py-1.5 rounded-md text-sm font-medium transition-all duration-200 ${subChart === s
                    ? (s === 'volume' ? 'bg-blue-600 text-white' : s === 'rsi' ? 'bg-orange-600 text-white' : 'bg-purple-600 text-white') + ' shadow-lg scale-105'
                    : 'bg-gray-700/50 text-gray-400 hover:bg-gray-700 hover:text-gray-200'
                    }`}
                >
                  {s === 'volume' ? '成交量' : s === 'rsi' ? 'RSI' : '乖離率'}
                </button>
              ))}
            </div>

            <div className="w-full border border-gray-700 rounded min-h-[450px]">
              {chartData.length > 0 ? (
                <TVChart data={chartData} interval={interval} subChart={subChart} />
              ) : (
                <div className="flex items-center justify-center h-[450px] text-gray-500 bg-gray-900">
                  載入圖台中...
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Technical Indicators */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 sm:gap-6 mb-4 sm:mb-6">
          <div className="bg-gray-800 rounded-lg shadow-lg border border-gray-700 p-6">
            <h2 className="text-xl font-bold text-gray-100 mb-4">主圖指標</h2>
            <div className="space-y-3">
              <div className="flex justify-between">
                <span className="text-gray-400">現價</span>
                <span className="font-semibold">{formatPrice(displayPrice)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">MA20</span>
                <span className="font-semibold">{formatPrice(indicators?.ma20)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">MA50</span>
                <span className="font-semibold">{formatPrice(indicators?.ma50)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">布林通道上</span>
                <span className="font-semibold">{formatPrice(indicators?.bb_upper)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">布林通道下</span>
                <span className="font-semibold">{formatPrice(indicators?.bb_lower)}</span>
              </div>
            </div>
          </div>

          <div className="bg-gray-800 rounded-lg shadow-lg border border-gray-700 p-6">
            <h2 className="text-xl font-bold text-gray-100 mb-4">副圖指標</h2>
            <div className="space-y-3">
              <div className="flex justify-between items-center">
                <span className="text-gray-400 flex items-center gap-1.5">
                  14 日 RSI
                  <EducationalHint glossaryId="rsi-indicator" />
                </span>
                <span className="font-semibold text-orange-500">{indicators?.rsi ? indicators.rsi.toFixed(2) : '---'}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-gray-400 flex items-center gap-1.5">
                  20 日乖離率
                  <EducationalHint glossaryId="bias-indicator" />
                </span>
                <span className={`font-semibold ${indicators?.bias_ma20 >= 0 ? 'text-rose-500' : 'text-emerald-400'}`}>
                  {indicators?.bias_ma20 ? `${indicators.bias_ma20.toFixed(2)}%` : '---'}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-gray-400 flex items-center gap-1.5">
                  9 日 KD 指標
                  <EducationalHint glossaryId="kd-indicator" />
                </span>
                {id && <KDIndicator stockId={id as string} />}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
