'use client';

import React, { useEffect, useRef, useState } from 'react';

// 改為動態引入類型
import type { Time as LWTime, IChartApi, IPriceLine } from 'lightweight-charts';

export interface KLineData {
    time: LWTime;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
    originalTime: number; // 原始時間戳
    rsi?: number;
    bias?: number;
    isUp: boolean;
    color?: string;
    wickColor?: string;
    borderColor?: string;
}

interface TVChartProps {
    data: KLineData[];
    interval?: string;
    subChart?: 'volume' | 'rsi' | 'bias';
    colors?: {
        backgroundColor?: string;
        textColor?: string;
        upColor?: string;
        downColor?: string;
    };
}

// 計算移動平均線的輔助函數
function calculateMA(data: KLineData[], period: number) {
    const maData = [];
    for (let i = 0; i < data.length; i++) {
        if (i < period - 1) {
            continue;
        }
        let sum = 0;
        for (let j = 0; j < period; j++) {
            sum += data[i - j].close;
        }
        maData.push({
            time: data[i].time,
            value: sum / period,
        });
    }
    return maData;
}

export default function TVChart({ data, interval = '1d', subChart = 'volume', colors = {} }: TVChartProps) {
    const {
        backgroundColor = '#1f2937',
        textColor = '#f3f4f6',
        upColor = '#f43f5e',
        downColor = '#34d399',
    } = colors;

    const chartContainerRef = useRef<HTMLDivElement>(null);
    const chartRef = useRef<IChartApi | null>(null);
    const dataRef = useRef<KLineData[]>(data);
    const highPriceLineRef = useRef<IPriceLine | null>(null);
    const lowPriceLineRef = useRef<IPriceLine | null>(null);
    const lastLabelRef = useRef<HTMLDivElement | null>(null);
    const [isMounted, setIsMounted] = useState(false);
    const [visibleBars, setVisibleBars] = useState(200);
    const [legendValues, setLegendValues] = useState<{ ma5: number | null, ma10: number | null, ma20: number | null }>({
        ma5: null, ma10: null, ma20: null
    });

    useEffect(() => {
        dataRef.current = data;
    }, [data]);

    useEffect(() => {
        setIsMounted(true);
        // 響應式預設值
        if (typeof window !== 'undefined') {
            const isMobile = window.innerWidth < 768;
            setVisibleBars(isMobile ? 30 : 200);
        }
    }, []);

    const handleZoom = (step: number) => {
        if (!chartRef.current) return;
        const newBars = Math.max(10, Math.min(500, visibleBars + step));
        setVisibleBars(newBars);

        const timeScale = chartRef.current.timeScale();
        if (dataRef.current.length > 0) {
            timeScale.setVisibleLogicalRange({
                from: dataRef.current.length - newBars,
                to: dataRef.current.length - 1,
            });
        }
    };

    useEffect(() => {
        if (!isMounted || !chartContainerRef.current) return;

        let isDisposed = false;

        const handleResize = () => {
            if (chartContainerRef.current && chartRef.current && !isDisposed) {
                chartRef.current.applyOptions({ width: chartContainerRef.current.clientWidth });
            }
        };

        const initChart = async () => {
            const { createChart, ColorType, CandlestickSeries, HistogramSeries, LineSeries } = await import('lightweight-charts');

            if (isDisposed || !chartContainerRef.current) return;

            const isIntraday = ['30m', '1h'].includes(interval);

            const chart = createChart(chartContainerRef.current, {
                layout: {
                    background: { type: ColorType.Solid, color: backgroundColor },
                    textColor,
                },
                grid: {
                    vertLines: { visible: false },
                    horzLines: { visible: false },
                },
                crosshair: {
                    mode: 0, // CrosshairMode.Normal
                },
                width: chartContainerRef.current.clientWidth,
                height: 400,
                localization: {
                    timeFormatter: (time: LWTime) => {
                        // 1. 如果是純整數物理索引 (0, 1, 2...)
                        const index = Math.floor(Number(time));
                        if (typeof time === 'number' && index < dataRef.current.length && index >= 0) {
                            const originalTime = (dataRef.current[index] as any).originalTime;
                            if (originalTime) {
                                const date = new Date((originalTime + 8 * 3600) * 1000);
                                const h = String(date.getUTCHours());
                                const min = String(date.getUTCMinutes()).padStart(2, '0');
                                return `${date.getUTCFullYear()}/${date.getUTCMonth() + 1}/${date.getUTCDate()} ${h}:${min}`;
                            }
                        }
                        // 2. 如果是傳統時間戳
                        if (typeof time === 'number' && time > 1100000000) {
                            const date = new Date((time + 8 * 3600) * 1000);
                            const y = date.getUTCFullYear();
                            const m = String(date.getUTCMonth() + 1);
                            const d = String(date.getUTCDate());
                            if (isIntraday) {
                                const h = String(date.getUTCHours());
                                const min = String(date.getUTCMinutes()).padStart(2, '0');
                                return `${y}/${m}/${d} ${h}:${min}`;
                            }
                            return `${y}/${m}/${d}`;
                        }
                        return String(time);
                    },
                },
                timeScale: {
                    visible: true,
                    timeVisible: true,
                    secondsVisible: false,
                    fixLeftEdge: false, // 允許向左滑動查看歷史
                    fixRightEdge: true,
                    // 動態調整 X 軸標籤
                    shiftVisibleRangeOnNewBar: true,
                    rightOffset: 5,
                    tickMarkFormatter: (time: LWTime, tickMarkType?: number) => {
                        let targetDate: Date | null = null;
                        const index = Math.floor(Number(time));

                        // 1. 如果是純整數物理索引 (0, 1, 2...)
                        if (typeof time === 'number' && index < dataRef.current.length && index >= 0) {
                            const originalTime = (dataRef.current[index] as any).originalTime;
                            if (originalTime) {
                                targetDate = new Date((originalTime + 8 * 3600) * 1000);
                            }
                        }
                        // 2. 如果是傳統時間戳
                        if (!targetDate && typeof time === 'number' && time > 1100000000) {
                            targetDate = new Date((time + 8 * 3600) * 1000);
                        }

                        if (targetDate) {
                            const month = String(targetDate.getUTCMonth() + 1);
                            const day = String(targetDate.getUTCDate());
                            const hours = String(targetDate.getUTCHours());
                            const minutes = String(targetDate.getUTCMinutes()).padStart(2, '0');

                            if (tickMarkType === 2) return `${month}/${day}`; // Month
                            if (interval === '1d' || interval === '1wk' || interval === '1mo') {
                                if (tickMarkType === 0) return String(targetDate.getUTCFullYear()); // Year
                                return `${month}/${day}`;
                            }
                            // 日內線：如果是開盤時間則顯示日期，否則顯示時間
                            return (hours === '9' && minutes === '00') ? `${month}/${day}` : `${hours}:${minutes}`;
                        }
                        return String(time);
                    },
                },
            });

            chartRef.current = chart;

            // 1. 先建立成交量序列 (若有)，確保其在底層
            let volumeSeries: any = null;
            if (subChart === 'volume') {
                volumeSeries = chart.addSeries(HistogramSeries, {
                    color: '#6b7280',
                    priceFormat: {
                        type: 'custom',
                        formatter: (price: number) => {
                            const lots = price / 100;
                            if (lots >= 10000) return `${(lots / 10000).toFixed(1)} 萬`;
                            if (lots >= 1) return `${Math.floor(lots)} 張`;
                            return `${price} 股`;
                        },
                    },
                    priceScaleId: 'volume',
                    lastValueVisible: false,
                    priceLineVisible: false, // 隱藏最後一筆的水平線
                });

                chart.priceScale('volume').applyOptions({
                    visible: false,
                    scaleMargins: { top: 0.8, bottom: 0 },
                });

                volumeSeries.setData(data.map(d => ({
                    time: d.time,
                    value: d.volume,
                    color: '#6b7280',
                })));
            }

            // 2. 建立 K 線序列，這會疊加在成交量之上
            const candlestickSeries = chart.addSeries(CandlestickSeries, {
                upColor, downColor, borderVisible: false, wickUpColor: upColor, wickDownColor: downColor,
                priceLineVisible: false,
                lastValueVisible: false,
                priceFormat: {
                    type: 'custom',
                    formatter: (price: number) => {
                        // Y 軸標籤不要顯示小數點 (依據要求，這裡統一格式化為整數或自訂標籤)
                        return Math.round(price).toLocaleString();
                    },
                },
            });

            candlestickSeries.setData(data.map(d => ({
                time: d.time,
                open: d.open,
                high: d.high,
                low: d.low,
                close: d.close,
                color: d.color,
                wickColor: d.wickColor,
                borderColor: d.borderColor,
            })));

            // 3. 建立均線序列，疊加在最上層
            const ma5Data = calculateMA(data, 5);
            const ma10Data = calculateMA(data, 10);
            const ma20Data = calculateMA(data, 20);

            // 使用更暗一點的配色
            const ma5Series = chart.addSeries(LineSeries, { color: '#94a3b8', lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
            const ma10Series = chart.addSeries(LineSeries, { color: '#ca8a04', lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
            const ma20Series = chart.addSeries(LineSeries, { color: '#0891b2', lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });

            ma5Series.setData(ma5Data);
            ma10Series.setData(ma10Data);
            ma20Series.setData(ma20Data);

            // 建立快速查詢 Map
            const ma5Map = new Map(ma5Data.map(d => [d.time, d.value]));
            const ma10Map = new Map(ma10Data.map(d => [d.time, d.value]));
            const ma20Map = new Map(ma20Data.map(d => [d.time, d.value]));

            const updateLegend = (param: any) => {
                if (isDisposed) return;

                const validCrosshair = param && param.time !== undefined && param.point !== undefined && param.point.x >= 0 && param.point.y >= 0;
                const targetTime = validCrosshair ? param.time : data[data.length - 1].time;

                setLegendValues({
                    ma5: ma5Map.get(targetTime) || null,
                    ma10: ma10Map.get(targetTime) || null,
                    ma20: ma20Map.get(targetTime) || null,
                });
            };

            chart.subscribeCrosshairMove(updateLegend);
            // 初始顯示最後一筆
            updateLegend(null);

            // 4. 其他指標處理 (RSI/Bias 依然在成交量位置)
            if (subChart === 'rsi') {
                const rsiSeries = chart.addSeries(LineSeries, {
                    color: '#f97316',
                    lineWidth: 2,
                    priceScaleId: 'rsi',
                    priceLineVisible: false, // 隱藏指標水平線
                    lastValueVisible: false,
                });

                const rsiData = data
                    .map(d => ({
                        time: d.time,
                        value: d.rsi,
                    }))
                    .filter((d): d is { time: LWTime; value: number } => d.value !== undefined && d.value !== null);

                rsiSeries.setData(rsiData);

                rsiSeries.createPriceLine({ price: 70, color: '#ef4444', lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: '超買(70)' });
                rsiSeries.createPriceLine({ price: 30, color: '#10b981', lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: '超賣(30)' });

                chart.priceScale('rsi').applyOptions({
                    visible: false,
                    scaleMargins: { top: 0.8, bottom: 0 }
                });
            } else if (subChart === 'bias') {
                const biasSeries = chart.addSeries(HistogramSeries, {
                    priceScaleId: 'bias',
                    priceFormat: { type: 'custom', formatter: (price: number) => `${price.toFixed(2)}%` },
                    priceLineVisible: false,
                    lastValueVisible: false,
                });

                const biasData = data
                    .map(d => ({
                        time: d.time,
                        value: d.bias,
                        color: (d.bias && d.bias > 0) ? upColor : downColor,
                    }))
                    .filter((d): d is { time: LWTime; value: number; color: string } => d.value !== undefined && d.value !== null);

                biasSeries.setData(biasData);

                chart.priceScale('bias').applyOptions({
                    visible: false,
                    scaleMargins: { top: 0.8, bottom: 0 }
                });
            }

            // 動態標示圖中的最高價與最低價
            const updateHighLowMarkers = () => {
                const logicalRange = chart.timeScale().getVisibleLogicalRange();
                if (!logicalRange) return;

                const from = Math.max(0, Math.floor(logicalRange.from));
                const to = Math.min(data.length - 1, Math.ceil(logicalRange.to));

                let visibleHigh = -Infinity;
                let visibleLow = Infinity;

                for (let i = from; i <= to; i++) {
                    const price = data[i];
                    if (price.high > visibleHigh) visibleHigh = price.high;
                    if (price.low < visibleLow) visibleLow = price.low;
                }

                if (visibleHigh !== -Infinity) {
                    if (highPriceLineRef.current) candlestickSeries.removePriceLine(highPriceLineRef.current);
                    highPriceLineRef.current = candlestickSeries.createPriceLine({
                        price: visibleHigh,
                        color: 'rgba(239, 68, 68, 0.4)', // 更淡的顏色
                        lineWidth: 1,
                        lineStyle: 1, // Dotted
                        axisLabelVisible: true,
                        title: 'H',
                    });
                }

                if (visibleLow !== Infinity) {
                    if (lowPriceLineRef.current) candlestickSeries.removePriceLine(lowPriceLineRef.current);
                    lowPriceLineRef.current = candlestickSeries.createPriceLine({
                        price: visibleLow,
                        color: 'rgba(16, 185, 129, 0.4)', // 更淡的顏色
                        lineWidth: 1,
                        lineStyle: 1, // Dotted
                        axisLabelVisible: true,
                        title: 'L',
                    });
                }
            };

            chart.timeScale().subscribeVisibleLogicalRangeChange(updateHighLowMarkers);

            // 初始顯示範圍
            const timeScale = chart.timeScale();
            if (data.length > 0) {
                const initialBars = window.innerWidth < 768 ? 40 : 200;
                if (data.length > initialBars) {
                    timeScale.setVisibleLogicalRange({
                        from: data.length - initialBars,
                        to: data.length - 1,
                    });
                } else {
                    timeScale.fitContent();
                }
            }

            // 初次呼叫標示最高最低價
            setTimeout(updateHighLowMarkers, 100);

            // 確保最新一筆資料的 X 軸標籤永遠顯示
            const updateLastLabel = () => {
                if (!lastLabelRef.current || !chartContainerRef.current || isDisposed) return;
                const lastIndex = data.length - 1;
                const x = chart.timeScale().logicalToCoordinate(lastIndex);
                if (x === null || x < 0 || x > chartContainerRef.current.clientWidth) {
                    lastLabelRef.current.style.opacity = '0';
                    return;
                }
                const lastBar = data[lastIndex];
                const originalTime = (lastBar as any).originalTime;
                let dateStr = '';
                if (originalTime) {
                    const date = new Date((originalTime + 8 * 3600) * 1000);
                    dateStr = `${date.getUTCMonth() + 1}/${date.getUTCDate()}`;
                } else if (typeof lastBar.time === 'string') {
                    const parts = (lastBar.time as string).split('-');
                    dateStr = `${parseInt(parts[1])}/${parseInt(parts[2])}`;
                }
                lastLabelRef.current.textContent = dateStr;
                lastLabelRef.current.style.left = `${x}px`;
                lastLabelRef.current.style.opacity = '1';
            };
            chart.timeScale().subscribeVisibleLogicalRangeChange(updateLastLabel);
            setTimeout(updateLastLabel, 150);

            window.addEventListener('resize', handleResize);
        };

        initChart();

        return () => {
            isDisposed = true;
            window.removeEventListener('resize', handleResize);
            if (chartRef.current) {
                chartRef.current.remove();
                chartRef.current = null;
            }
        };
    }, [isMounted, backgroundColor, textColor, upColor, downColor, interval, data, subChart]);

    if (!isMounted) {
        return <div className="w-full h-[400px] bg-[#1f2937] animate-pulse rounded flex items-center justify-center text-gray-500">載入圖表中...</div>;
    }

    return (
        <div className="w-full flex flex-col">
            {/* MA Legend (置於圖形外框上方，寬度對應) */}
            <div className="w-full flex flex-row items-center gap-4 mb-1 px-4 py-1.5 bg-gray-800/50 rounded-t border-b border-gray-700/50 text-[11px] md:text-[12px] font-mono whitespace-nowrap overflow-x-auto no-scrollbar">
                <div className="flex items-center gap-1.5 min-w-fit">
                    <span className="w-2 h-2 rounded-full bg-[#94a3b8]"></span>
                    <span className="text-[#94a3b8]">MA5: <span className="text-gray-100">{legendValues.ma5 ? legendValues.ma5.toFixed(1) : '--'}</span></span>
                </div>
                <div className="flex items-center gap-1.5 min-w-fit">
                    <span className="w-2 h-2 rounded-full bg-[#ca8a04]"></span>
                    <span className="text-[#ca8a04]">MA10: <span className="text-gray-100">{legendValues.ma10 ? legendValues.ma10.toFixed(1) : '--'}</span></span>
                </div>
                <div className="flex items-center gap-1.5 min-w-fit">
                    <span className="w-2 h-2 rounded-full bg-[#0891b2]"></span>
                    <span className="text-[#0891b2]">MA20: <span className="text-gray-100">{legendValues.ma20 ? legendValues.ma20.toFixed(1) : '--'}</span></span>
                </div>
            </div>

            <div className="relative w-full min-h-[400px]">
                {/* 縮放控制按鈕 (保持在圖表內左上角) */}
                <div className="absolute top-4 left-4 z-10 flex flex-row gap-2">
                    <button
                        onClick={() => handleZoom(-10)}
                        className="w-8 h-8 bg-gray-700/80 hover:bg-gray-600 text-white rounded shadow-lg flex items-center justify-center transition-colors border border-gray-600 pointer-events-auto"
                        title="放大 (減少筆數)"
                    >
                        <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                            <path fillRule="evenodd" d="M10 5a1 1 0 011 1v3h3a1 1 0 110 2h-3v3a1 1 0 11-2 0v-3H6a1 1 0 110-2h3V6a1 1 0 011-1z" clipRule="evenodd" />
                        </svg>
                    </button>
                    <button
                        onClick={() => handleZoom(10)}
                        className="w-8 h-8 bg-gray-700/80 hover:bg-gray-600 text-white rounded shadow-lg flex items-center justify-center transition-colors border border-gray-600 pointer-events-auto"
                        title="縮小 (增加筆數)"
                    >
                        <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                            <path fillRule="evenodd" d="M5 10a1 1 0 011-1h8a1 1 0 110 2H6a1 1 0 01-1-1z" clipRule="evenodd" />
                        </svg>
                    </button>
                </div>
                <div ref={chartContainerRef} className="w-full h-[400px]" />
                {/* 最新一筆 X 軸標籤 overlay */}
                <div
                    ref={lastLabelRef}
                    className="absolute z-10 text-[11px] pointer-events-none"
                    style={{ opacity: 0, transform: 'translateX(-50%)', bottom: '4px', color: textColor, fontSize: '13px' }}
                />
            </div>
        </div>
    );
}
