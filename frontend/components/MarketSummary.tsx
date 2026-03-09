import React, { useState, useEffect } from 'react';
import api from '../lib/api';
import EducationalHint from './EducationalHint';
import { formatPrice } from '../lib/formatters';

interface MarketSummaryData {
    taiex_price: number;
    taiex_change: number;
    taiex_change_percent: number;
    taiex_volume: number;
    avg_volume_5d: number;
    volume_ratio: number;
    advances: number;
    declines: number;
    unchanged: number;
    limit_up: number;
    limit_down: number;
    advance_decline_ratio: number;
    market_sentiment: string;
    volume_status: string;
    data_date: string;
    is_live: boolean;
    last_updated: string;
}

/**
 * 大盤指數概況組件（單卡片版）
 *
 * 在一張卡片內整合加權指數、成交量、多空比三大資訊
 */
export default function MarketSummary() {
    const [data, setData] = useState<MarketSummaryData | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(false);
    const [flashClass, setFlashClass] = useState("");
    const prevPriceRef = React.useRef<number | null>(null);

    useEffect(() => {
        const fetchSummary = async () => {
            try {
                const res = await api.get('/market/summary');
                const newData = res.data;

                // 價格跳動動畫邏輯
                if (prevPriceRef.current !== null && newData.taiex_price !== prevPriceRef.current) {
                    const direction = newData.taiex_price > prevPriceRef.current ? "up" : "down";
                    setFlashClass(direction === "up" ? "bg-rose-500/20" : "bg-emerald-500/20");
                    setTimeout(() => setFlashClass(""), 800);
                }

                prevPriceRef.current = newData.taiex_price;
                setData(newData);
            } catch (err) {
                console.error('Failed to fetch market summary', err);
                setError(true);
            } finally {
                setLoading(false);
            }
        };

        fetchSummary();

        // 台灣時區處理：只有在交易時間 (平日 09:00 - 15:00) 才啟動輪詢
        const now = new Date();
        const day = now.getDay();
        const hour = now.getHours();
        const isTradingDay = day >= 1 && day <= 5;
        const isTradingHour = hour >= 9 && hour < 15;

        let interval: NodeJS.Timeout | null = null;
        if (isTradingDay && isTradingHour) {
            interval = setInterval(fetchSummary, 60000);
        }

        return () => {
            if (interval) clearInterval(interval);
        };
    }, []);

    if (loading) {
        return (
            <div className="bg-zinc-900/60 backdrop-blur-md rounded-2xl border border-white/5 p-6 animate-pulse">
                <div className="h-8 bg-zinc-700/50 rounded w-48 mb-3" />
                <div className="h-5 bg-zinc-700/50 rounded w-32" />
            </div>
        );
    }

    if (error || !data) {
        return (
            <div className="bg-zinc-900/40 backdrop-blur-md rounded-2xl border border-white/5 p-5 text-center">
                <p className="text-zinc-500 text-sm">市場資料載入失敗，請稍後重試</p>
            </div>
        );
    }

    const isUp = data.taiex_change >= 0;
    // 台股習慣：紅漲綠跌
    const changeColor = isUp ? 'text-rose-500' : 'text-emerald-400';
    const changeArrow = isUp ? '▲' : '▼';

    return (
        <div className={`relative overflow-hidden bg-gradient-to-br ${isUp ? 'from-rose-900/20 to-zinc-900/80' : 'from-emerald-900/30 to-zinc-900/80'} backdrop-blur-md rounded-2xl border border-white/10 px-6 py-5 shadow-xl transition-colors duration-500 ${flashClass}`}>
            {/* 背景裝飾 */}
            <div className="absolute -right-10 -top-10 w-40 h-40 rounded-full bg-white/[0.015]" />

            {/* 主要內容區 */}
            <div className="relative z-10 flex flex-col text-white">
                {/* 標題與小統計 */}
                <div className="flex items-center justify-between mb-1.5 sm:mb-2.5">
                    <div className="flex items-center gap-2">
                        <span className="text-xl sm:text-2xl font-black tracking-widest uppercase text-white">加權指數</span>
                        <div className="inline-flex text-zinc-400 opacity-50 hover:opacity-100 transition-opacity ml-1">
                            <EducationalHint glossaryId="taiex" />
                        </div>
                    </div>

                    {/* 漲跌家數小標籤 */}
                    <div className="flex items-center gap-x-3 sm:gap-x-4">
                        <span className="text-zinc-500 font-bold text-[10px] uppercase tracking-tighter">0050</span>
                        <div className="flex items-center gap-x-3 sm:gap-x-4">
                            <div className="flex items-baseline gap-1">
                                <span className="text-zinc-400 font-bold text-sm sm:text-base">平</span>
                                <span className="text-zinc-300 font-black font-mono text-lg sm:text-xl">{data.unchanged}</span>
                            </div>
                            <div className="flex items-baseline gap-1">
                                <span className="text-rose-500 font-bold text-sm sm:text-base">漲</span>
                                <span className="text-rose-400 font-black font-mono text-lg sm:text-xl">{data.advances}</span>
                            </div>
                            <div className="flex items-baseline gap-1">
                                <span className="text-emerald-500 font-bold text-sm sm:text-base">跌</span>
                                <span className="text-emerald-400 font-black font-mono text-lg sm:text-xl">{data.declines}</span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            {/* 指數價格與漲跌幅 */}
            <div className="flex items-center justify-between w-full">
                <span className="text-4xl sm:text-5xl font-black tracking-tight font-mono">
                    {formatPrice(data.taiex_price)}
                </span>
                <div className="flex flex-col items-end gap-1 sm:gap-1.5 pt-0.5">
                    <span className={`text-xl sm:text-2xl font-black font-mono leading-none ${changeColor}`}>
                        {changeArrow} {Math.abs(data.taiex_change).toFixed(2)}
                    </span>
                    <span className={`text-lg sm:text-xl font-black font-mono leading-none ${changeColor} opacity-90`}>
                        {isUp ? '+' : ''}{data.taiex_change_percent.toFixed(2)}%
                    </span>
                </div>
            </div>
            {/* 底部整合狀態與時間戳記 */}
            <div className="absolute bottom-3 left-6 flex items-center gap-2 pointer-events-none">
                <div className={`w-1.5 h-1.5 rounded-full ${data.is_live ? 'bg-emerald-500 animate-pulse shadow-[0_0_5px_rgba(16,185,129,0.8)]' : 'bg-zinc-600'}`}></div>
                <span className="text-[9px] font-mono tracking-widest text-zinc-500 opacity-40">
                    {data.is_live ? `RT: ${data.last_updated}` : `EOD: ${data.data_date}`}
                </span>
            </div>
        </div>
    );
}
