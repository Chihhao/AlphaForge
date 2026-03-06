'use client';

import React, { useEffect, useRef, useState } from 'react';

// 改為動態引入類型，避免頂部直接 import 執行檔
import type { Time as LWTime, IChartApi, ISeriesApi } from 'lightweight-charts';

export interface KLineData {
    time: LWTime;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
    isUp: boolean;
    color?: string;
    wickColor?: string;
    borderColor?: string;
}

interface TVChartProps {
    data: KLineData[];
    interval?: string;
    range?: string;
    colors?: {
        backgroundColor?: string;
        textColor?: string;
        upColor?: string;
        downColor?: string;
    };
}

export default function TVChart({ data, interval = '1d', range = '1d', colors = {} }: TVChartProps) {
    const {
        backgroundColor = '#1f2937',
        textColor = '#f3f4f6',
        upColor = '#f43f5e',
        downColor = '#34d399',
    } = colors;

    const chartContainerRef = useRef<HTMLDivElement>(null);
    const chartRef = useRef<IChartApi | null>(null);
    const [isMounted, setIsMounted] = useState(false);

    useEffect(() => {
        setIsMounted(true);
    }, []);

    useEffect(() => {
        if (!isMounted || !chartContainerRef.current) return;

        let isDisposed = false;

        const handleResize = () => {
            if (chartContainerRef.current && chartRef.current && !isDisposed) {
                chartRef.current.applyOptions({ width: chartContainerRef.current.clientWidth });
            }
        };

        const initChart = async () => {
            // 在此處動態載入執行檔，確保頂層補丁已生效
            const { createChart, ColorType, CandlestickSeries, HistogramSeries } = await import('lightweight-charts');

            if (isDisposed || !chartContainerRef.current) return;

            const isIntraday = ['1m', '5m', '15m', '1h'].includes(interval);

            const chart = createChart(chartContainerRef.current, {
                layout: {
                    background: { type: ColorType.Solid, color: backgroundColor },
                    textColor,
                },
                grid: {
                    vertLines: { color: '#374151' },
                    horzLines: { color: '#374151' },
                },
                width: chartContainerRef.current.clientWidth,
                height: 400,
                localization: {
                    timeFormatter: (time: LWTime) => {
                        if (typeof time === 'number') {
                            const date = new Date((time + 8 * 3600) * 1000);
                            const y = date.getUTCFullYear();
                            const m = String(date.getUTCMonth() + 1);
                            const d = String(date.getUTCDate());
                            const h = String(date.getUTCHours());
                            const min = String(date.getUTCMinutes()).padStart(2, '0');

                            if (isIntraday) {
                                return `${y}/${m}/${d} ${h}:${min}`;
                            } else {
                                return `${y}/${m}/${d}`;
                            }
                        }
                        return String(time);
                    },
                },
                timeScale: {
                    timeVisible: true,
                    secondsVisible: false,
                    fixLeftEdge: true,
                    fixRightEdge: true,
                    tickMarkFormatter: (time: LWTime, tickMarkType?: number) => {
                        if (typeof time === 'number') {
                            const date = new Date((time + 8 * 3600) * 1000);
                            const year = date.getUTCFullYear().toString();
                            const month = String(date.getUTCMonth() + 1);
                            const day = String(date.getUTCDate());
                            const hours = String(date.getUTCHours());
                            const minutes = String(date.getUTCMinutes()).padStart(2, '0');

                            if (tickMarkType === 0) return year;
                            if (tickMarkType === 1) return `${year}/${month}`;
                            if (tickMarkType === 2) return `${month}/${day}`;

                            // Time tick or default fallback
                            if (range === '1d') {
                                return `${hours}:${minutes}`;
                            } else if (range === '5d' || range === '1mo') {
                                if (interval === '1d') return `${month}/${day}`;
                                return `${month}/${day} ${hours}:${minutes}`;
                            } else if (range === '3mo' || range === '1y') {
                                if (interval === '1h') return `${month}/${day} ${hours}:00`;
                                return `${year}/${month}/${day}`;
                            } else if (range === '3y' || range === '5y') {
                                return `${year}/${month}`;
                            }

                            return `${month}/${day}`;
                        }
                        return String(time);
                    },
                },
            });

            chartRef.current = chart;
            chart.timeScale().fitContent();

            const candlestickSeries = chart.addSeries(CandlestickSeries, {
                upColor, downColor, borderVisible: false, wickUpColor: upColor, wickDownColor: downColor,
                priceFormat: {
                    type: 'custom',
                    formatter: (price: number) => {
                        if (price >= 1000) return Math.round(price).toLocaleString(undefined, { maximumFractionDigits: 0 });
                        if (price >= 100) return price.toFixed(1);
                        return price.toFixed(2);
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

            const volumeSeries = chart.addSeries(HistogramSeries, {
                color: '#34d399',
                priceFormat: {
                    type: 'custom',
                    formatter: (price: number) => {
                        const shares = price; // 假設後端回傳為「股數」
                        const lots = shares / 1000; // 轉為「張數」
                        if (lots >= 10000) {
                            return `${(lots / 10000).toFixed(1)} 萬`;
                        }
                        if (lots >= 1) {
                            return `${Math.floor(lots)} 張`;
                        }
                        // 如果小於 1 張代表可能是零股交易
                        return `${shares} 股`;
                    },
                },
                priceScaleId: '',
            });

            chart.priceScale('').applyOptions({
                scaleMargins: { top: 0.8, bottom: 0 },
            });

            volumeSeries.setData(data.map(d => ({
                time: d.time,
                value: d.volume,
                color: d.color || (d.isUp ? upColor : downColor),
            })));

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
    }, [isMounted, backgroundColor, textColor, upColor, downColor, interval, data, range]);

    if (!isMounted) {
        return <div className="w-full h-[400px] bg-[#1f2937] animate-pulse rounded flex items-center justify-center text-gray-500">初始化圖表中...</div>;
    }

    return <div ref={chartContainerRef} className="w-full h-full min-h-[400px]" />;
}
