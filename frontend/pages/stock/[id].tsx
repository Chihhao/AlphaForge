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

  const [range, setRange] = useState<'1d' | '5d' | '1mo' | '3mo' | '1y' | '3y' | '5y'>('5d')
  const [interval, setInterval] = useState<'1m' | '5m' | '15m' | '1h' | '1d'>('15m')
  const [quote, setQuote] = useState<any>(null)
  const [chartData, setChartData] = useState<Array<any>>([])
  const [indicators, setIndicators] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [subChart, setSubChart] = useState<'volume' | 'rsi' | 'bias'>('volume')

  // 定義範圍與頻率的約束配置
  const RANGE_CONFIG = {
    '1d': { allowed: ['1m', '5m', '15m'], default: '1m' },
    '5d': { allowed: ['1m', '5m', '15m', '1h'], default: '15m' },
    '1mo': { allowed: ['5m', '15m', '1h', '1d'], default: '1h' },
    '3mo': { allowed: ['1h', '1d'], default: '1d' },
    '1y': { allowed: ['1h', '1d'], default: '1d' },
    '3y': { allowed: ['1d'], default: '1d' },
    '5y': { allowed: ['1d'], default: '1d' },
  } as const;

  // 移除 useEffect 自動切換，改在 onClick 中處理，以避免 React state 造成的 Race condition

  useEffect(() => {
    if (!id) return

    // 防呆：確保當前的 interval 是該 range 允許的，否則不發送請求（等待 state 更新）
    const isAllowed = (RANGE_CONFIG[range].allowed as readonly string[]).includes(interval);
    if (!isAllowed) return;

    const fetchData = async () => {
      setLoading(true)
      try {
        // Fetch quote data for the current id
        const qres = await api.get(`/stocks/${id}/quote`)
        setQuote(qres.data)

        const kres = await api.get(`/stocks/${id}/kline?period=${range}&interval=${interval}`)
        const kd = kres.data
        const data = (kd.data || []).map((r: any, index: number, array: any[]) => {
          const date = new Date(r.date);
          if (isNaN(date.getTime())) return null;
          const ts = Math.floor(date.getTime() / 1000);

          // 台灣股市 K 線顏色邏輯：
          // 1. 收盤 > 開盤 => 紅色 (Up)
          // 2. 收盤 < 開盤 => 綠色 (Down)
          // 3. 收盤 == 開盤 => 參考前一根 K 線的收盤價
          //    - 收盤 > 前收 => 紅色
          //    - 收盤 < 前收 => 綠色
          //    - 收盤 == 前收 => 灰色/保持

          let isUp = r.close > r.open;
          let isDown = r.close < r.open;

          if (r.close === r.open) {
            if (index > 0) {
              const prevClose = array[index - 1].close;
              isUp = r.close > prevClose;
              isDown = r.close < prevClose;
            } else if (quote?.open_price) {
              // 第一根且開收相等，參考開盤價（通常開盤價是昨收，或參考 quote）
              isUp = r.close >= quote.open_price;
              isDown = r.close < quote.open_price;
            } else {
              isUp = true; // 預設紅色
            }
          }

          const upColor = '#f43f5e';
          const downColor = '#34d399';
          const neutralColor = '#9ca3af'; // gray-400

          const barColor = isUp ? upColor : (isDown ? downColor : neutralColor);

          return {
            time: ts as any,
            open: r.open,
            high: r.high,
            low: r.low,
            close: r.close,
            volume: r.volume,
            isUp: isUp || (!isDown), // 用於成交量顏色，預設紅色
            color: barColor,
            wickColor: barColor,
            borderColor: barColor
          };
        }).filter(Boolean) as any[]

        // Ensure no duplicate timestamps and sorted
        const uniqueData = data.filter((v: any, i: number, a: any[]) => a.findIndex(t => (t.time === v.time)) === i)
        uniqueData.sort((a: any, b: any) => a.time - b.time)

        const ires = await api.get(`/stocks/${id}/indicators?period=${range}&interval=${interval}`)
        const indData = ires.data

        // Merge indicators into chartData
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
          const ind = indMap.get(d.time)
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
  }, [id, range, interval])

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
            {/* Range & Interval Selectors */}
            <div className="space-y-4 mb-6">
              {/* Range Selector */}
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider mr-2">觀察範圍</span>
                {(['1d', '5d', '1mo', '3mo', '1y', '3y', '5y'] as const).map(p => (
                  <button
                    key={p}
                    onClick={() => {
                      setRange(p);
                      // 同步檢查並更新 interval，確保 React batch update
                      const isIntervalAllowed = (RANGE_CONFIG[p].allowed as readonly string[]).includes(interval);
                      if (!isIntervalAllowed) {
                        setInterval(RANGE_CONFIG[p].default);
                      }
                    }}
                    className={`px-3 py-1.5 rounded-md text-sm font-medium transition-all duration-200 ${range === p
                      ? 'bg-gold-600 text-gray-900 shadow-lg shadow-gold-900/20 scale-105'
                      : 'bg-gray-700/50 text-gray-400 hover:bg-gray-700 hover:text-gray-200'
                      }`}
                  >
                    {p === '1d' ? '今日' : p === '5d' ? '5日' : p === '1mo' ? '1月' : p === '3mo' ? '3月' : p === '1y' ? '1年' : p === '3y' ? '3年' : '5年'}
                  </button>
                ))}
              </div>

              {/* Interval Selector */}
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider mr-2">K 線頻率</span>
                {(['1m', '5m', '15m', '1h', '1d'] as const).map(i => {
                  const isAllowed = (RANGE_CONFIG[range].allowed as readonly string[]).includes(i);
                  return (
                    <button
                      key={i}
                      onClick={() => setInterval(i)}
                      disabled={!isAllowed}
                      className={`px-3 py-1.5 rounded-md text-sm font-medium transition-all duration-200 ${interval === i
                        ? 'bg-blue-600 text-white shadow-lg shadow-blue-900/20'
                        : isAllowed
                          ? 'bg-gray-700/50 text-gray-400 hover:bg-gray-700 hover:text-gray-200'
                          : 'bg-gray-800/20 text-gray-600 cursor-not-allowed opacity-50'
                        }`}
                    >
                      {i === '1m' ? '1分' : i === '5m' ? '5分' : i === '15m' ? '15分' : i === '1h' ? '1時' : '日'}
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

            {/* Chart Container */}
            <div className="h-[400px] w-full border border-gray-700 rounded overflow-hidden">
              {chartData.length > 0 ? (
                <TVChart data={chartData} interval={interval} range={range} subChart={subChart} />
              ) : (
                <div className="flex items-center justify-center h-[400px] text-gray-500 bg-gray-900">
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
