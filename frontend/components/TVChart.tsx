import React, { useEffect, useRef } from 'react';
import { createChart, ColorType, ISeriesApi, Time, CandlestickSeries, HistogramSeries } from 'lightweight-charts';

export interface KLineData {
    time: Time;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
    isUp: boolean; // Computed or from data
}

interface TVChartProps {
    data: KLineData[];
    colors?: {
        backgroundColor?: string;
        textColor?: string;
        upColor?: string;
        downColor?: string;
    };
}

export default function TVChart({ data, colors = {} }: TVChartProps) {
    const {
        backgroundColor = '#1f2937', // gray-800
        textColor = '#f3f4f6',       // gray-100
        upColor = '#ef5350', // Red for Taiwan stocks up
        downColor = '#26a69a', // Green for Taiwan stocks down
    } = colors;

    const chartContainerRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (!chartContainerRef.current) return;

        const handleResize = () => {
            chart.applyOptions({ width: chartContainerRef.current?.clientWidth });
        };

        const chart = createChart(chartContainerRef.current, {
            layout: {
                background: { type: ColorType.Solid, color: backgroundColor },
                textColor,
            },
            grid: {
                vertLines: { color: '#374151' }, // gray-700
                horzLines: { color: '#374151' },
            },
            width: chartContainerRef.current.clientWidth,
            height: 400,
            timeScale: {
                timeVisible: true,
                secondsVisible: false,
            },
        });

        chart.timeScale().fitContent();

        const candlestickSeries = chart.addSeries(CandlestickSeries, {
            upColor: upColor,
            downColor: downColor,
            borderVisible: false,
            wickUpColor: upColor,
            wickDownColor: downColor,
        });

        // Extract candlestick data
        const kData = data.map(d => ({
            time: d.time,
            open: d.open,
            high: d.high,
            low: d.low,
            close: d.close,
        }));

        candlestickSeries.setData(kData);

        // Add Volume histogram
        const volumeSeries = chart.addSeries(HistogramSeries, {
            color: '#26a69a',
            priceFormat: {
                type: 'volume',
            },
            priceScaleId: '', // set as an overlay by setting a blank priceScaleId
        });

        // Scale volume so it doesn't overlap candles too much
        chart.priceScale('').applyOptions({
            scaleMargins: {
                top: 0.8, // highest point of the series will be at 80% of the chart height
                bottom: 0,
            },
        });

        const vData = data.map(d => ({
            time: d.time,
            value: d.volume,
            color: d.isUp ? upColor : downColor,
        }));

        volumeSeries.setData(vData);

        window.addEventListener('resize', handleResize);

        return () => {
            window.removeEventListener('resize', handleResize);
            chart.remove();
        };
    }, [data, backgroundColor, textColor, upColor, downColor]);

    return <div ref={chartContainerRef} className="w-full h-full min-h-[400px]" />;
}
