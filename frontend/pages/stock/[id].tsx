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

  const [interval, setInterval] = useState<'30m' | '1h' | '1d' | '1wk' | '1mo'>('1d')
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
        // 30m: 60d (yfinance 限制)
        // 1h: 2y
        // 1d: 5y
        // 1wk, 1mo: max
        let period = '5y';
        if (interval === '30m') period = '60d';
        else if (interval === '1h') period = '2y';
        else if (interval === '1wk' || interval === '1mo') period = 'max';

        const kres = await api.get(`/stocks/${id}/kline?period=${period}&interval=${interval}`)
        const isIntraday = ['30m', '1h'].includes(interval);

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
      <div className="max-w-7xl mx-auto px-0 sm:px-6 lg:px-8 py-0 sm:py-6">
        {/* Stock Header */}
        <div className="bg-gray-800 rounded-none sm:rounded-lg shadow-lg border-b border-x-0 sm:border border-gray-700 p-4 sm:p-6 mb-0 sm:mb-6">
          <div className="flex justify-between items-center mb-3">
            <div>
              <h1 className="text-2xl sm:text-4xl font-bold text-gray-100 leading-tight">
                {displayName}
                <span className="text-gray-500 text-base font-normal ml-2">{id}</span>
              </h1>
            </div>
            <div className="text-right">
              <p className="text-2xl sm:text-4xl font-bold text-gray-100 tabular-nums">{formatPrice(displayPrice)}</p>
              <p className={`text-base sm:text-xl font-semibold tabular-nums ${displayChange >= 0 ? 'text-rose-500' : 'text-emerald-400'}`}>
                {displayChange >= 0 ? '+' : ''}{displayChange.toFixed(2)}%
              </p>
            </div>
          </div>

          <div className="-mx-4 sm:mx-0 border-t border-gray-700 mb-0" />
          <div className="grid grid-cols-4 gap-2 pt-3">
            <div>
              <p className="text-base text-gray-500">開盤</p>
              <p className="text-lg sm:text-xl font-semibold tabular-nums">{formatPrice(quote?.open_price)}</p>
            </div>
            <div>
              <p className="text-base text-gray-500">最高</p>
              <p className="text-lg sm:text-xl font-semibold tabular-nums">{formatPrice(quote?.high_price)}</p>
            </div>
            <div>
              <p className="text-base text-gray-500">最低</p>
              <p className="text-lg sm:text-xl font-semibold tabular-nums">{formatPrice(quote?.low_price)}</p>
            </div>
            <div>
              <p className="text-base text-gray-500">成交量</p>
              <p className="text-lg sm:text-xl font-semibold tabular-nums">
                {quote?.volume
                  ? (() => {
                    const lots = quote.volume / 1000;
                    return lots >= 10000
                      ? (lots / 10000).toFixed(1) + '萬張'
                      : Math.floor(lots).toLocaleString() + '張';
                  })()
                  : '---'}
              </p>
            </div>
          </div>
        </div>

        {/* Chart Section */}
        <div className="bg-gray-800 rounded-none sm:rounded-lg shadow-lg border-b border-x-0 sm:border border-gray-700 p-4 sm:p-6 mb-0 sm:mb-6">
          {/* Selectors: interval + sub-chart in one row */}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2 mb-3">
            <div className="flex items-center gap-1">
              {(['30m', '1h', '1d', '1wk', '1mo'] as const).map(i => (
                <button
                  key={i}
                  onClick={() => setInterval(i)}
                  className={`px-3 py-1.5 rounded text-base font-medium transition-colors ${interval === i
                    ? 'bg-blue-600 text-white'
                    : 'text-gray-400 hover:text-gray-200'
                  }`}
                >
                  {i === '30m' ? '30分' : i === '1h' ? '時' : i === '1d' ? '日' : i === '1wk' ? '週' : '月'}
                </button>
              ))}
            </div>
            <span className="text-gray-700">|</span>
            <div className="flex items-center gap-1">
              {(['volume', 'rsi', 'bias'] as const).map(s => (
                <button
                  key={s}
                  onClick={() => setSubChart(s)}
                  className={`px-3 py-1.5 rounded text-base font-medium transition-colors ${subChart === s
                    ? (s === 'volume' ? 'bg-blue-600' : s === 'rsi' ? 'bg-orange-600' : 'bg-purple-600') + ' text-white'
                    : 'text-gray-400 hover:text-gray-200'
                  }`}
                >
                  {s === 'volume' ? '量' : s === 'rsi' ? 'RSI' : '乖離'}
                </button>
              ))}
            </div>
          </div>

          <div className="-mx-4 sm:mx-0 border-y border-x-0 sm:border sm:rounded border-gray-700 min-h-[450px]">
            {chartData.length > 0 ? (
              <TVChart data={chartData} interval={interval} subChart={subChart} />
            ) : (
              <div className="flex items-center justify-center h-[450px] text-gray-500 bg-gray-900">
                載入圖表中...
              </div>
            )}
          </div>
        </div>

        {/* Fundamental Section */}
        <div className="bg-gray-800 rounded-none sm:rounded-lg shadow-lg border-b border-x-0 sm:border border-gray-700 p-4 sm:p-6 mb-0 sm:mb-6">
          <div className="grid grid-cols-2 md:grid-cols-3 gap-x-4 gap-y-0">
            {/* 價值評估 */}
            <div>
              <p className="text-sm font-bold text-gray-500 uppercase tracking-widest border-l-2 border-blue-500 pl-1.5 mb-2">估值</p>
              <div className="flex justify-between items-center py-1.5 border-b border-gray-700/50">
                <span className="text-base text-gray-400 flex items-center gap-1">本益比 <EducationalHint glossaryId="pe-ratio" /></span>
                <span className="font-mono text-lg text-gray-100">{quote?.pe_ratio ? quote.pe_ratio.toFixed(1) : '---'}</span>
              </div>
              <div className="flex justify-between items-center py-1.5">
                <span className="text-base text-gray-400 flex items-center gap-1">股價淨值比 <EducationalHint glossaryId="pb-ratio" /></span>
                <span className="font-mono text-lg text-gray-100">{quote?.pb_ratio ? quote.pb_ratio.toFixed(2) : '---'}</span>
              </div>
            </div>

            {/* 獲利與配息 */}
            <div>
              <p className="text-sm font-bold text-gray-500 uppercase tracking-widest border-l-2 border-rose-500 pl-1.5 mb-2">獲利</p>
              <div className="flex justify-between items-center py-1.5 border-b border-gray-700/50">
                <span className="text-base text-gray-400 flex items-center gap-1">權益報酬率 <EducationalHint glossaryId="roe-indicator" /></span>
                <span className={`font-mono text-sm ${quote?.roe >= 10 ? 'text-cyan-400' : 'text-gray-100'}`}>
                  {quote?.roe ? `${quote.roe.toFixed(1)}%` : '---'}
                </span>
              </div>
              <div className="flex justify-between items-center py-1.5">
                <span className="text-base text-gray-400 flex items-center gap-1">現金殖利率 <EducationalHint glossaryId="dividend-yield" /></span>
                <span className={`font-mono text-sm ${quote?.yield_rate >= 5 ? 'text-rose-400' : 'text-gray-100'}`}>
                  {quote?.yield_rate ? `${quote.yield_rate.toFixed(1)}%` : '---'}
                </span>
              </div>
            </div>

            {/* 營收動能 */}
            <div className="col-span-2 md:col-span-1 mt-3 md:mt-0">
              <p className="text-sm font-bold text-gray-500 uppercase tracking-widest border-l-2 border-emerald-500 pl-1.5 mb-2">營收</p>
              <div className="flex justify-between items-center py-1.5 border-b border-gray-700/50">
                <span className="text-base text-gray-400">單月 (億)</span>
                <span className="font-mono text-lg text-gray-100">{quote?.last_revenue ? quote.last_revenue.toLocaleString() : '---'}</span>
              </div>
              <div className="flex justify-between items-center py-1.5">
                <span className="text-base text-gray-400">年增率</span>
                <span className={`font-mono text-sm ${quote?.revenue_growth_yoy > 0 ? 'text-rose-400' : quote?.revenue_growth_yoy < 0 ? 'text-emerald-400' : 'text-gray-100'}`}>
                  {quote?.revenue_growth_yoy ? `${quote.revenue_growth_yoy > 0 ? '+' : ''}${quote.revenue_growth_yoy.toFixed(1)}%` : '---'}
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Technical Signal Card */}
        {(() => {
          const price = displayPrice
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
            if (rsi > 30) return { label: `RSI ${rsi.toFixed(1)}`, sub: '中性偏弱', color: 'text-gray-400' }
            return { label: `RSI ${rsi.toFixed(1)}`, sub: '超賣區，留意反彈', color: 'text-cyan-400' }
          })() : null

          const bbSignal = price && bbUpper && bbLower ? (() => {
            const pos = (price - bbLower) / (bbUpper - bbLower)
            const pct = (pos * 100).toFixed(0)
            if (pos > 0.85) return { label: `布林 ${pct}%`, sub: '接近上軌，注意追高', color: 'text-amber-400' }
            if (pos > 0.5)  return { label: `布林 ${pct}%`, sub: '通道上半段，偏多', color: 'text-rose-400' }
            if (pos > 0.15) return { label: `布林 ${pct}%`, sub: '通道下半段，偏弱', color: 'text-gray-400' }
            return { label: `布林 ${pct}%`, sub: '接近下軌，留意支撐', color: 'text-cyan-400' }
          })() : null

          const rows = [
            { key: 'trend', name: '均線位階', hint: 'ma-indicator' as string | null, signal: trendSignal },
            { key: 'rsi',   name: 'RSI',      hint: 'rsi-indicator' as string | null, signal: rsiSignal },
            { key: 'bb',    name: '布林通道',  hint: null,                             signal: bbSignal },
          ]

          return (
            <div className="bg-gray-800 rounded-none sm:rounded-lg shadow-lg border-b border-x-0 sm:border border-gray-700 p-4 sm:p-6 mb-0 sm:mb-6">
              <p className="text-sm font-bold text-gray-500 uppercase tracking-widest mb-3">技術面信號</p>
              <div>
                {rows.map(({ key, name, hint, signal }) => (
                  <div key={key} className="flex justify-between items-center py-2.5 border-b border-gray-700/40">
                    <span className="text-base text-gray-400 flex items-center gap-1.5">
                      {name}
                      {hint && <EducationalHint glossaryId={hint} />}
                    </span>
                    {signal
                      ? <div className="text-right">
                          <p className={`font-mono text-base font-semibold ${signal.color}`}>{signal.label}</p>
                          <p className="text-xs text-gray-500">{signal.sub}</p>
                        </div>
                      : <span className="text-gray-600">---</span>
                    }
                  </div>
                ))}
                <div className="flex justify-between items-center py-2.5">
                  <span className="text-base text-gray-400 flex items-center gap-1.5">
                    KD 指標
                    <EducationalHint glossaryId="kd-indicator" />
                  </span>
                  {id && <KDIndicator stockId={id as string} />}
                </div>
              </div>
            </div>
          )
        })()}
      </div>
    </div>
  )
}
